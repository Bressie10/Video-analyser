"""Company-scoped history, idempotency claims, and atomic frozen evidence writes."""
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb


def idea(db, company_id, idea_id):
    row = db.execute('SELECT * FROM ideas WHERE company_id=%s AND id=%s',
                     (company_id, idea_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Idea was not found.')
    row.pop('evidence_sealed')
    # Large frozen inputs are exposed only by the separate evidence endpoint.
    for key in ('profile_evidence', 'prior_idea_evidence'):
        row.pop(key)
    row['target_platforms'] = [r['platform'] for r in db.execute(
        'SELECT platform FROM idea_target_platforms WHERE idea_id=%s ORDER BY platform',
        (idea_id,)).fetchall()]
    row['publications'] = db.execute('''SELECT library_item_id,created_at FROM idea_publications
        WHERE idea_id=%s ORDER BY created_at,library_item_id''', (idea_id,)).fetchall()
    return row


def history(db, company_id, limit, after=None, *, search=None, status=None,
            feedback=None, target_platform=None, created_from=None, created_to=None):
    cursor = None
    if after is not None:
        cursor = db.execute('SELECT created_at,id FROM ideas WHERE company_id=%s AND id=%s',
                            (company_id, after)).fetchone()
        if cursor is None:
            raise HTTPException(404, 'History cursor was not found.')
    clauses = ['i.company_id=%s']
    params = [company_id]
    if cursor:
        clauses.append('(i.created_at,i.id)<(%s,%s)')
        params.extend([cursor['created_at'], after])
    if search and search.strip():
        # Literal case-insensitive substring search; SQL wildcard characters
        # carry no special meaning. Search includes the explicitly saved script.
        clauses.append("strpos(lower(i.title || ' ' || i.concept || ' ' || i.script), lower(%s))>0")
        params.append(search.strip())
    for field, value in (('status', status), ('feedback', feedback)):
        if value is not None:
            clauses.append(f'i.{field}=%s')
            params.append(value)
    if target_platform is not None:
        clauses.append('EXISTS (SELECT 1 FROM idea_target_platforms t WHERE t.idea_id=i.id AND t.platform=%s)')
        params.append(target_platform)
    if created_from is not None:
        clauses.append('i.created_at>=%s')
        params.append(created_from)
    if created_to is not None:
        clauses.append('i.created_at<%s')
        params.append(created_to)
    rows = db.execute(f'''SELECT i.id,i.title,i.concept,i.status,i.feedback,i.feedback_reason,
        i.created_at,i.updated_at,ARRAY(SELECT t.platform FROM idea_target_platforms t
            WHERE t.idea_id=i.id ORDER BY t.platform) AS target_platforms
        FROM ideas i WHERE {' AND '.join(clauses)}
        ORDER BY i.created_at DESC,i.id DESC LIMIT %s''', (*params, limit + 1)).fetchall()
    return {'items': rows[:limit], 'next_cursor': rows[limit-1]['id'] if len(rows) > limit else None}


def claim_request(db, company_id, request_id, request_hash):
    db.execute('''INSERT INTO idea_generation_requests(company_id,request_id,request_hash)
        VALUES (%s,%s,%s) ON CONFLICT DO NOTHING''', (company_id, request_id, request_hash))
    row = db.execute('''SELECT *,lease_until>clock_timestamp() AS active
        FROM idea_generation_requests WHERE company_id=%s AND request_id=%s FOR UPDATE''',
        (company_id, request_id)).fetchone()
    if row['request_hash'] != request_hash:
        raise HTTPException(409, 'Request ID was already used with different inputs.')
    saved = db.execute('SELECT id FROM ideas WHERE company_id=%s AND request_id=%s',
                       (company_id, request_id)).fetchone()
    if saved:
        return None, idea(db, company_id, saved['id'])
    if row['active']:
        raise HTTPException(409, 'Generation is in progress; retry this request later.')
    claim = uuid4()
    db.execute('''UPDATE idea_generation_requests SET claim=%s,
        lease_until=clock_timestamp()+interval '5 minutes' WHERE company_id=%s AND request_id=%s''',
        (claim, company_id, request_id))
    return claim, None


def release_claim(db, company_id, request_id, claim):
    db.execute('''UPDATE idea_generation_requests SET claim=NULL,lease_until=NULL
        WHERE company_id=%s AND request_id=%s AND claim=%s''', (company_id, request_id, claim))


def persist(db, company_id, body, request_hash, claim, capture, result, model,
            recommendation_version, evidence_schema_version):
    row = db.execute('''SELECT claim FROM idea_generation_requests
        WHERE company_id=%s AND request_id=%s FOR UPDATE''',
        (company_id, body.request_id)).fetchone()
    if row is None or row['claim'] != claim:
        raise HTTPException(409, 'Generation claim expired; retry the same request.')
    payload = capture['payload']
    identity = db.execute('''INSERT INTO ideas(company_id,title,concept,script,generation_brief,
        recommendation_version,model,evidence_schema_version,evidence_captured_at,request_id,
        request_hash,profile_revision_id,profile_evidence,prior_idea_evidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
        (company_id, result.title, result.concept, result.script, body.generation_brief,
         recommendation_version, model, evidence_schema_version, capture['captured_at'],
         body.request_id, request_hash, payload['profile_revision_id'],
         Jsonb(payload['company_profile']) if payload['company_profile'] is not None else None,
         Jsonb(payload['prior_ideas']))).fetchone()['id']
    for source in payload['videos']:
        db.execute('''INSERT INTO idea_sources(idea_id,library_item_id,source_order,analysis_version,
            analysis_payload,publication_context) VALUES (%s,%s,%s,%s,%s,%s)''',
            (identity, source['library_item_id'], source['source_order'], source['analysis_version'],
             Jsonb(source['analysis_payload']), Jsonb(source['publication_context'])))
    for snapshot in payload['performance_snapshots']:
        db.execute('''INSERT INTO idea_performance_evidence(idea_id,library_item_id,snapshot,
            fetched_at,attribution,publication_context) VALUES (%s,%s,%s,%s,%s,%s)''',
            (identity, snapshot['library_item_id'], Jsonb(snapshot['snapshot']),
             snapshot['fetched_at'], snapshot['attribution'], Jsonb(snapshot['publication_context'])))
    for source in payload['videos']:
        for owner in source['performance_ids']:
            db.execute('INSERT INTO idea_source_performance VALUES (%s,%s,%s)',
                       (identity, source['library_item_id'], owner))
    for platform in payload['target_platforms']:
        db.execute('INSERT INTO idea_target_platforms VALUES (%s,%s)', (identity, platform))
    db.execute('UPDATE ideas SET evidence_sealed=true WHERE id=%s', (identity,))
    release_claim(db, company_id, body.request_id, claim)
    return idea(db, company_id, identity)


def frozen_evidence(db, company_id, idea_id):
    saved = idea(db, company_id, idea_id)
    row = db.execute('SELECT profile_evidence,prior_idea_evidence FROM ideas WHERE id=%s',
                     (idea_id,)).fetchone()
    sources = db.execute('''SELECT library_item_id,source_order,analysis_version,analysis_payload,
        publication_context FROM idea_sources WHERE idea_id=%s ORDER BY source_order''',
        (idea_id,)).fetchall()
    mappings = db.execute('''SELECT source_library_item_id,performance_library_item_id
        FROM idea_source_performance WHERE idea_id=%s ORDER BY performance_library_item_id''',
        (idea_id,)).fetchall()
    for source in sources:
        source['performance_ids'] = [m['performance_library_item_id'] for m in mappings
                                    if m['source_library_item_id'] == source['library_item_id']]
    performance = db.execute('''SELECT library_item_id,snapshot,fetched_at,attribution,publication_context
        FROM idea_performance_evidence WHERE idea_id=%s ORDER BY library_item_id''', (idea_id,)).fetchall()
    return {
        'videos': sources, 'performance_snapshots': performance,
        'company_profile': row['profile_evidence'], 'profile_revision_id': saved['profile_revision_id'],
        'prior_ideas': row['prior_idea_evidence'], 'generation_brief': saved['generation_brief'],
        'target_platforms': saved['target_platforms'],
    }


def edit(db, company_id, idea_id, changes):
    # Names are strictly from IdeaEdit, never interpolated from arbitrary input.
    fields = [field for field in ('title', 'concept', 'script', 'status') if field in changes]
    assignments = ','.join(f'{field}=%s' for field in fields)
    row = db.execute(f'UPDATE ideas SET {assignments} WHERE company_id=%s AND id=%s RETURNING id',
                     (*[changes[field] for field in fields], company_id, idea_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Idea was not found.')
    return idea(db, company_id, idea_id)


def set_feedback(db, company_id, idea_id, feedback, reason):
    row = db.execute('''UPDATE ideas SET feedback=%s,feedback_reason=%s
        WHERE company_id=%s AND id=%s RETURNING id''',
        (feedback, reason, company_id, idea_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Idea was not found.')
    return idea(db, company_id, idea_id)


def add_publication(db, company_id, idea_id, item_id):
    """Caller holds live company/item authorization locks in this transaction."""
    db.execute('''INSERT INTO idea_publications(idea_id,library_item_id)
        SELECT id,%s FROM ideas WHERE company_id=%s AND id=%s
        ON CONFLICT DO NOTHING''', (item_id, company_id, idea_id))
    # The scoped read also distinguishes duplicate links from missing/foreign ideas.
    return idea(db, company_id, idea_id)


def remove_publication(db, company_id, idea_id, item_id):
    # No current item authorization is needed to remove one's historical link.
    # Company authorization (including the archive check) is still mandatory.
    db.execute('''DELETE FROM idea_publications p USING ideas i
        WHERE p.idea_id=i.id AND i.company_id=%s AND i.id=%s AND p.library_item_id=%s''',
        (company_id, idea_id, item_id))
    return idea(db, company_id, idea_id)
