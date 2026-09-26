"""Company-scoped cache revisions, transactional invalidation and durable refreshes."""

from uuid import uuid4

from psycopg.types.json import Jsonb

from app.meta_library_repository import database
from app import company_profile_types as policy


REASONS = frozenset({
    'new_content', 'analysis_changed', 'performance_changed', 'relationship_changed',
    'account_assignment', 'account_unassignment', 'evidence_removed', 'version_upgrade',
})
RESTRICTIVE_REASONS = {'account_unassignment', 'evidence_removed', 'account_assignment'}


def lock_company(db, company_id):
    # Global order: connection row -> company advisory lock -> profile/job rows.
    # Ownership writers hold this connection FOR UPDATE before changing access.
    # Taking the shared connection lock first avoids inversion with their hooks.
    db.execute('''SELECT c.id FROM meta_connections c JOIN companies company
        ON company.connection_id=c.id WHERE company.id=%s FOR SHARE OF c''', (company_id,))
    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 72419401))', (str(company_id),))


def ensure_profiles(db, company_id):
    lock_company(db, company_id)
    for scope in policy.SCOPES:
        db.execute('''INSERT INTO company_profiles(company_id,scope,generator_version,schema_version)
            VALUES (%s,%s,%s,%s) ON CONFLICT(company_id,scope) DO NOTHING''',
            (company_id, scope, policy.GENERATOR_VERSION, policy.SCHEMA_VERSION))


def profile(db, company_id, scope):
    return db.execute('SELECT * FROM company_profiles WHERE company_id=%s AND scope=%s',
                      (company_id, scope)).fetchone()


def enqueue(db, profile_id, *, expedite=False):
    row = db.execute('''SELECT * FROM company_profile_jobs WHERE profile_id=%s
        AND state IN ('queued','running')''', (profile_id,)).fetchone()
    if row:
        if expedite and row['state'] == 'queued':
            db.execute('''UPDATE company_profile_jobs SET available_at=now(),attempts=0
                WHERE id=%s''', (row['id'],))
        return row['id'], True
    row = db.execute('INSERT INTO company_profile_jobs(profile_id) VALUES (%s) RETURNING id',
                     (profile_id,)).fetchone()
    return row['id'], False


def invalidate(db, company_id, scopes, reason, *, event_key=None):
    """Call in the source write transaction. Event keys identify whole events, not scopes."""
    scopes = set(scopes)
    if not scopes or not scopes <= set(policy.SCOPES) or reason not in REASONS:
        raise ValueError('Invalid profile invalidation.')
    if reason in RESTRICTIVE_REASONS:
        # Assignment/removal may change creative evidence in any platform.
        scopes = set(policy.SCOPES)
    elif scopes & set(policy.PLATFORMS):
        scopes.add('shared')
    ensure_profiles(db, company_id)
    if event_key is not None:
        inserted = db.execute('''INSERT INTO company_profile_invalidations(company_id,event_key)
            VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING event_key''',
            (company_id, event_key)).fetchone()
        if inserted is None:
            return False
    for scope in sorted(scopes):
        row = db.execute('''UPDATE company_profiles SET input_revision=input_revision+1,
            suppressed=suppressed OR %s,invalidation_reason=%s,updated_at=now(),
            generator_version=%s,schema_version=%s WHERE company_id=%s AND scope=%s RETURNING id''',
            (reason in RESTRICTIVE_REASONS, reason, policy.GENERATOR_VERSION,
             policy.SCHEMA_VERSION, company_id, scope)).fetchone()
        enqueue(db, row['id'])
    return True


def refresh(db, company_id, scope, key):
    ensure_profiles(db, company_id)
    row = profile(db, company_id, scope)
    prior = db.execute('''SELECT job_id FROM company_profile_refresh_requests
        WHERE profile_id=%s AND idempotency_key=%s''', (row['id'], key)).fetchone()
    if prior:
        return {'job_id': prior['job_id'], 'coalesced': True, 'idempotent_replay': True}
    if scope == 'shared':
        for platform in policy.PLATFORMS:
            candidate = profile(db, company_id, platform)
            if freshness(candidate) != 'fresh':
                enqueue(db, candidate['id'], expedite=True)
    job_id, coalesced = enqueue(db, row['id'], expedite=True)
    db.execute('''INSERT INTO company_profile_refresh_requests(profile_id,idempotency_key,job_id)
        VALUES (%s,%s,%s)''', (row['id'], key, job_id))
    return {'job_id': job_id, 'coalesced': coalesced, 'idempotent_replay': False}


def freshness(row):
    if not row or row['current_revision_id'] is None:
        return 'missing'
    if (row['suppressed'] or row['input_revision'] != row['validated_input_revision']
            or row['generator_version'] != policy.GENERATOR_VERSION
            or row['schema_version'] != policy.SCHEMA_VERSION):
        return 'stale'
    return 'fresh'


def read(db, company_id, scope, *, include_document=True):
    row = profile(db, company_id, scope)
    state = freshness(row)
    revision = None
    job = None
    if row:
        if row['current_revision_id']:
            revision = db.execute('SELECT * FROM company_profile_revisions WHERE profile_id=%s AND id=%s',
                                  (row['id'], row['current_revision_id'])).fetchone()
        job = db.execute('''SELECT id,state,attempts,outcome,error,available_at,lease_until
            FROM company_profile_jobs WHERE profile_id=%s ORDER BY created_at DESC,id DESC LIMIT 1''',
            (row['id'],)).fetchone()
    if scope == 'shared' and row:
        dependencies = db.execute('SELECT * FROM company_profiles WHERE company_id=%s AND scope<>%s',
                                  (company_id, 'shared')).fetchall()
        if any(freshness(p) != 'fresh' for p in dependencies):
            state = 'stale' if revision else 'missing'
    usable = bool(revision and not row['suppressed'])
    result = {'scope': scope, 'freshness': state, 'usable': usable,
              'input_revision': row['input_revision'] if row else 0,
              'validated_input_revision': row['validated_input_revision'] if row else 0,
              'job': job, 'revision': None}
    if usable:
        result['revision'] = {k: revision[k] for k in (
            'id', 'revision_number', 'input_revision', 'generator_version', 'schema_version',
            'model', 'created_at', 'dependencies')}
        result['coverage'] = revision['document']['coverage']
        if include_document:
            result['document'] = revision['document']
            result['evidence_manifest'] = revision['evidence_manifest']
    return result


def claim():
    with database() as db:
        job = db.execute('''SELECT j.*,p.company_id,p.scope,p.input_revision AS latest_input_revision FROM company_profile_jobs j
            JOIN company_profiles p ON p.id=j.profile_id
            JOIN companies c ON c.id=p.company_id
            WHERE c.archived_at IS NULL AND ((j.state='queued' AND j.available_at<=now())
               OR (j.state='running' AND j.lease_until<now()))
            ORDER BY CASE WHEN p.scope='shared' THEN 1 ELSE 0 END,j.available_at,j.created_at,j.id
            LIMIT 1''').fetchone()
        if not job:
            return None
        # Take the same company -> job lock order as invalidation/publication.
        # In particular, exhausting a lease must not strand a concurrent invalidation.
        lock_company(db, job['company_id'])
        job = db.execute('''SELECT j.*,p.company_id,p.scope,p.input_revision AS latest_input_revision
            FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
            JOIN companies c ON c.id=p.company_id
            WHERE c.archived_at IS NULL AND j.id=%s AND ((j.state='queued' AND j.available_at<=now())
                OR (j.state='running' AND j.lease_until<now()))
            FOR UPDATE OF j SKIP LOCKED''', (job['id'],)).fetchone()
        if not job:
            return None
        attempts = job['attempts']
        if job['captured_input_revision'] is not None and job['captured_input_revision'] != job['latest_input_revision']:
            attempts = 0
        if attempts >= policy.MAX_ATTEMPTS:
            db.execute("""UPDATE company_profile_jobs SET state='failed',lease_until=NULL,
                finished_at=now(),error='Profile lease recovery limit reached.' WHERE id=%s""", (job['id'],))
            return None
        claim_id = uuid4()
        db.execute('''UPDATE company_profile_jobs SET state='running',claim=%s,
            attempts=%s,captured_input_revision=%s,lease_until=now()+%s*interval '1 second' WHERE id=%s''',
            (claim_id, attempts + 1, job['latest_input_revision'], policy.LEASE_SECONDS, job['id']))
        return {**job, 'claim': claim_id, 'attempts': attempts + 1}


def live_job(db, job):
    return db.execute('''SELECT id FROM company_profile_jobs WHERE id=%s AND claim=%s
        AND state='running' AND lease_until>now() FOR UPDATE''',
        (job['id'], job['claim'])).fetchone()


def renew(job):
    with database() as db:
        return db.execute('''UPDATE company_profile_jobs SET lease_until=now()+%s*interval '1 second'
            WHERE id=%s AND claim=%s AND state='running' AND lease_until>now() RETURNING id''',
            (policy.LEASE_SECONDS, job['id'], job['claim'])).fetchone() is not None


def retry_or_fail(job, *, permanent=False):
    with database() as db:
        lock_company(db, job['company_id'])
        if not live_job(db, job):
            return
        stored = db.execute('SELECT captured_input_revision FROM company_profile_jobs WHERE id=%s',
                            (job['id'],)).fetchone()
        current = profile(db, job['company_id'], job['scope'])
        if (stored['captured_input_revision'] is not None
                and stored['captured_input_revision'] != current['input_revision']):
            defer(db, job)
            return
        retry = not permanent and job['attempts'] < policy.MAX_ATTEMPTS
        db.execute('''UPDATE company_profile_jobs SET state=%s,error=%s,lease_until=NULL,
            available_at=now()+%s*interval '1 second',finished_at=CASE WHEN %s THEN NULL ELSE now() END
            WHERE id=%s''', ('queued' if retry else 'failed',
            'Temporary profile generation failure.' if retry else 'Profile generation failed.',
            policy.BACKOFF_SECONDS * 2 ** min(job['attempts'] - 1, policy.MAX_ATTEMPTS), retry, job['id']))


def defer(db, job):
    db.execute('''UPDATE company_profile_jobs SET state='queued',claim=NULL,lease_until=NULL,
        attempts=0,outcome='superseded',available_at=now()+%s*interval '1 second' WHERE id=%s''',
        (policy.POLL_SECONDS, job['id']))


def publish(db, job, captured, bundle, document, input_hash, model):
    """Caller holds company lock, valid claim, and has checked current source generation."""
    current = profile(db, job['company_id'], job['scope'])
    old = db.execute('SELECT * FROM company_profile_revisions WHERE id=%s',
                     (current['current_revision_id'],)).fetchone()
    reused = bool(old and old['input_hash'] == input_hash)
    revision_id = old['id'] if reused else uuid4()
    if not reused:
        db.execute('''INSERT INTO company_profile_revisions
            (id,profile_id,revision_number,input_revision,input_hash,assignment_version,
             generator_version,schema_version,model,document,evidence_manifest,dependencies)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (revision_id, current['id'], old['revision_number'] + 1 if old else 1,
             captured['input_revision'], input_hash, bundle['assignment_version'],
             policy.GENERATOR_VERSION, policy.SCHEMA_VERSION, model, Jsonb(document),
             Jsonb(bundle['manifest']), Jsonb(bundle['dependencies'])))
    db.execute('''UPDATE company_profiles SET current_revision_id=%s,validated_input_revision=%s,
        suppressed=false,generator_version=%s,schema_version=%s,updated_at=now() WHERE id=%s''',
        (revision_id, captured['input_revision'], policy.GENERATOR_VERSION, policy.SCHEMA_VERSION, current['id']))
    db.execute('''UPDATE company_profile_jobs SET state='completed',outcome=%s,error=NULL,
        captured_input_revision=%s,input_hash=%s,lease_until=NULL,finished_at=now() WHERE id=%s''',
        ('reused' if reused else 'generated', captured['input_revision'], input_hash, job['id']))
    if job['scope'] != 'shared' and not reused:
        invalidate(db, job['company_id'], ['shared'], 'analysis_changed')
    return revision_id


def schedule_versions():
    with database() as db:
        companies = db.execute('''SELECT DISTINCT p.company_id FROM company_profiles p
            JOIN companies c ON c.id=p.company_id WHERE c.archived_at IS NULL
            AND (p.generator_version<>%s OR p.schema_version<>%s) ORDER BY p.company_id LIMIT %s''',
            (policy.GENERATOR_VERSION, policy.SCHEMA_VERSION, policy.VERSION_SCAN_LIMIT)).fetchall()
        for row in companies:
            invalidate(db, row['company_id'], policy.SCOPES, 'version_upgrade')
