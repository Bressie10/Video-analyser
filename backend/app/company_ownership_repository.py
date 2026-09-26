"""Explicit company ownership and fail-closed company content readers.

Callers supply the connection ID obtained from existing Meta authentication, never
from an untrusted company payload. No provider discovery or inference happens here.
Public operations are transactional; connection locks serialize ownership changes
and keep multi-query reads stable against unlink/reassignment/archive/disconnect.

COMPANY_SCOPE_SQL is the shared scope for future repository queries. Its named
parameters are connection_id and company_id. direct_items identifies owned organic
items and assigned ads for metric access; accessible_items additionally grants
content-only access to assigned ad creatives. Use the sanitized readers below for
metadata: even an organic item's label may have been overwritten by V2 ad discovery.
Do not replace this distinction with a connection-wide traversal or V2 projection.
"""

from functools import wraps

from app import meta_library_repository as library


class CompanyNotFound(LookupError):
    """Unknown/foreign company, or archived company in a content operation."""


class OwnershipNotFound(LookupError):
    """Unknown/foreign resource or absent ownership relationship."""


class OwnershipConflict(ValueError):
    """An explicit release/reassignment is required."""


def _transaction(operation):
    @wraps(operation)
    def wrapped(db, *args, **kwargs):
        with db.transaction():
            return operation(db, *args, **kwargs)
    return wrapped


def _lock(db, connection_id, *, write=False):
    # Fixed SQL fragments only. Read locks also serialize against disconnect.
    mode = 'UPDATE' if write else 'SHARE'
    if db.execute(
        f'SELECT id FROM meta_connections WHERE id=%s FOR {mode}',
        (connection_id,),
    ).fetchone() is None:
        raise CompanyNotFound('Company was not found.')


def _company(db, connection_id, company_id, *, active=True, write=False):
    _lock(db, connection_id, write=write)
    row = db.execute(
        'SELECT * FROM companies WHERE id=%s AND connection_id=%s',
        (company_id, connection_id),
    ).fetchone()
    if row is None or (active and row['archived_at'] is not None):
        raise CompanyNotFound('Company was not found.')
    return row


def _account(db, connection_id, account_id):
    row = db.execute(
        'SELECT * FROM meta_accounts WHERE id=%s AND connection_id=%s',
        (account_id, connection_id),
    ).fetchone()
    if row is None:
        raise OwnershipNotFound('Account was not found.')
    return row


@_transaction
def create_company(db, connection_id, name):
    _lock(db, connection_id, write=True)
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Company name is required.')
    return db.execute(
        'INSERT INTO companies(connection_id,name) VALUES (%s,%s) RETURNING *',
        (connection_id, name.strip()),
    ).fetchone()


@_transaction
def list_companies(db, connection_id, *, include_archived=False):
    _lock(db, connection_id)
    return db.execute(
        '''SELECT * FROM companies WHERE connection_id=%s
        AND (%s OR archived_at IS NULL) ORDER BY created_at,id''',
        (connection_id, include_archived),
    ).fetchall()


@_transaction
def get_company(db, connection_id, company_id):
    return _company(db, connection_id, company_id, active=False)


@_transaction
def require_active_company(db, connection_id, company_id):
    """Authorize a live company with the connection supplied by authentication."""
    return _company(db, connection_id, company_id)


def _invalidate_profiles(db, company_id, reason):
    # 007 is required by the integrated company layer. Never commit an access
    # change if its suppression/invalidation could not be persisted.
    from app import company_profile_repository as profiles
    from app.company_profile_types import SCOPES

    profiles.invalidate(db, company_id, SCOPES, reason)


@_transaction
def set_company_archived(db, connection_id, company_id, *, archived=True):
    previous = _company(db, connection_id, company_id, active=False, write=True)
    row = db.execute(
        '''UPDATE companies SET archived_at=CASE WHEN %s
        THEN COALESCE(archived_at,now()) ELSE NULL END WHERE id=%s RETURNING *''',
        (archived, company_id),
    ).fetchone()
    if (previous['archived_at'] is not None) != archived:
        _invalidate_profiles(db, company_id, 'evidence_removed' if archived else 'account_assignment')
    return row


def _link(db, connection_id, company_id, account):
    if account['platform'] != 'meta_ads' and db.execute(
        '''SELECT 1 FROM company_accounts WHERE account_id=%s AND company_id<>%s''',
        (account['id'], company_id),
    ).fetchone():
        raise OwnershipConflict('Organic account already belongs to a company.')
    return db.execute(
        '''INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
        VALUES (%s,%s,%s,%s) ON CONFLICT (company_id,account_id) DO NOTHING RETURNING account_id''',
        (company_id, connection_id, account['id'], account['platform']),
    ).fetchone() is not None


@_transaction
def link_account(db, connection_id, company_id, account_id):
    _company(db, connection_id, company_id, write=True)
    if _link(db, connection_id, company_id, _account(db, connection_id, account_id)):
        _invalidate_profiles(db, company_id, 'account_assignment')


@_transaction
def unlink_account(db, connection_id, company_id, account_id):
    _company(db, connection_id, company_id, active=False, write=True)
    _account(db, connection_id, account_id)
    if db.execute(
        'SELECT 1 FROM company_ad_assignments WHERE company_id=%s AND account_id=%s',
        (company_id, account_id),
    ).fetchone():
        raise OwnershipConflict('Unassign or reassign ads before unlinking their account.')
    removed = db.execute(
        'DELETE FROM company_accounts WHERE company_id=%s AND account_id=%s RETURNING account_id',
        (company_id, account_id),
    ).fetchone()
    if removed:
        _invalidate_profiles(db, company_id, 'account_unassignment')


@_transaction
def reassign_organic_account(db, connection_id, source_company_id, target_company_id, account_id):
    _company(db, connection_id, source_company_id, active=False, write=True)
    _company(db, connection_id, target_company_id, write=True)
    account = _account(db, connection_id, account_id)
    if account['platform'] not in ('facebook', 'instagram'):
        raise OwnershipConflict('Only organic accounts have exclusive account ownership.')
    if not db.execute(
        'SELECT 1 FROM company_accounts WHERE company_id=%s AND account_id=%s',
        (source_company_id, account_id),
    ).fetchone():
        raise OwnershipNotFound('Account ownership was not found.')
    if source_company_id == target_company_id:
        return
    db.execute(
        'DELETE FROM company_accounts WHERE company_id=%s AND account_id=%s',
        (source_company_id, account_id),
    )
    _link(db, connection_id, target_company_id, account)
    for company in sorted((source_company_id, target_company_id)):
        _invalidate_profiles(db, company, 'account_unassignment' if company == source_company_id else 'account_assignment')


def _ad(db, connection_id, ad_item_id):
    row = db.execute(
        '''SELECT i.* FROM meta_library_items i JOIN meta_accounts a
        ON a.id=i.account_id AND a.connection_id=i.connection_id
        WHERE i.id=%s AND i.connection_id=%s AND i.content_type='ad'
        AND a.platform='meta_ads' ''',
        (ad_item_id, connection_id),
    ).fetchone()
    if row is None:
        raise OwnershipNotFound('Ad was not found.')
    return row


def _assign(db, connection_id, company_id, ad):
    if not db.execute(
        '''SELECT 1 FROM company_accounts WHERE company_id=%s AND connection_id=%s
        AND account_id=%s AND account_platform='meta_ads' ''',
        (company_id, connection_id, ad['account_id']),
    ).fetchone():
        raise OwnershipConflict('Link the Ads account before assigning its ad.')
    existing = db.execute(
        'SELECT company_id FROM company_ad_assignments WHERE ad_item_id=%s',
        (ad['id'],),
    ).fetchone()
    if existing and existing['company_id'] != company_id:
        raise OwnershipConflict('Ad already belongs to a company.')
    return db.execute(
        '''INSERT INTO company_ad_assignments(ad_item_id,company_id,connection_id,account_id)
        VALUES (%s,%s,%s,%s) ON CONFLICT (ad_item_id) DO NOTHING RETURNING ad_item_id''',
        (ad['id'], company_id, connection_id, ad['account_id']),
    ).fetchone() is not None


@_transaction
def assign_ad(db, connection_id, company_id, ad_item_id):
    _company(db, connection_id, company_id, write=True)
    if _assign(db, connection_id, company_id, _ad(db, connection_id, ad_item_id)):
        _invalidate_profiles(db, company_id, 'account_assignment')


@_transaction
def unassign_ad(db, connection_id, company_id, ad_item_id):
    _company(db, connection_id, company_id, active=False, write=True)
    _ad(db, connection_id, ad_item_id)
    # Never remove a different company's assignment.
    removed = db.execute(
        'DELETE FROM company_ad_assignments WHERE company_id=%s AND ad_item_id=%s RETURNING ad_item_id',
        (company_id, ad_item_id),
    ).fetchone()
    if removed:
        _invalidate_profiles(db, company_id, 'account_unassignment')


@_transaction
def reassign_ad(db, connection_id, source_company_id, target_company_id, ad_item_id):
    _company(db, connection_id, source_company_id, active=False, write=True)
    _company(db, connection_id, target_company_id, write=True)
    ad = _ad(db, connection_id, ad_item_id)
    if source_company_id == target_company_id:
        if not db.execute(
            'SELECT 1 FROM company_ad_assignments WHERE company_id=%s AND ad_item_id=%s',
            (source_company_id, ad_item_id),
        ).fetchone():
            raise OwnershipNotFound('Ad ownership was not found.')
        return
    if not db.execute(
        'DELETE FROM company_ad_assignments WHERE company_id=%s AND ad_item_id=%s RETURNING ad_item_id',
        (source_company_id, ad_item_id),
    ).fetchone():
        raise OwnershipNotFound('Ad ownership was not found.')
    _assign(db, connection_id, target_company_id, ad)
    for company in sorted((source_company_id, target_company_id)):
        _invalidate_profiles(db, company, 'account_unassignment' if company == source_company_id else 'account_assignment')


COMPANY_SCOPE_SQL = '''
WITH scope_company AS (
    SELECT id,connection_id FROM companies
    WHERE id=%(company_id)s AND connection_id=%(connection_id)s AND archived_at IS NULL
), valid_items AS (
    SELECT i.* FROM meta_library_items i
    JOIN scope_company c ON c.connection_id=i.connection_id
    JOIN meta_accounts a ON a.id=i.account_id AND a.connection_id=i.connection_id
), direct_items AS (
    SELECT i.* FROM valid_items i
    JOIN company_accounts ca ON ca.account_id=i.account_id AND ca.connection_id=i.connection_id
    JOIN scope_company c ON c.id=ca.company_id
    WHERE (i.content_type<>'ad' AND ca.account_platform IN ('facebook','instagram'))
    OR (i.content_type='ad' AND ca.account_platform='meta_ads' AND EXISTS (
        SELECT 1 FROM company_ad_assignments x
        WHERE x.ad_item_id=i.id AND x.company_id=c.id
        AND x.connection_id=i.connection_id AND x.account_id=i.account_id
    ))
), accessible_items AS (
    SELECT id FROM direct_items
    UNION
    SELECT asset.id FROM direct_items ad
    JOIN meta_ad_assets edge ON edge.ad_item_id=ad.id
    JOIN valid_items asset ON asset.id=edge.video_item_id
    WHERE ad.content_type='ad' AND asset.content_type<>'ad'
)
'''


def _params(connection_id, company_id, **extra):
    return dict(connection_id=connection_id, company_id=company_id, **extra)


def _selected(db, connection_id, company_id, item_id):
    row = db.execute(
        COMPANY_SCOPE_SQL + '''SELECT i.* FROM valid_items i
        JOIN accessible_items a ON a.id=i.id WHERE i.id=%(item_id)s''',
        _params(connection_id, company_id, item_id=item_id),
    ).fetchone()
    if row is None:
        raise OwnershipNotFound('Library item was not found.')
    return row


def _content_item(db, connection_id, row):
    # A creative label/error can have been populated from another ad during V2
    # discovery. Never expose these fields through a shared-content projection.
    fields = library.PUBLIC_FIELDS if row['content_type'] == 'ad' else (
        'id', 'platform', 'content_type', 'analysis_state', 'analysis_version', 'video_id',
    )
    result = {key: row[key] for key in fields}
    if row['video_id'] and not db.execute(
        'SELECT 1 FROM videos WHERE id=%s AND meta_connection_id=%s',
        (row['video_id'], connection_id),
    ).fetchone():
        result['video_id'] = None
    return result


@_transaction
def list_items(db, connection_id, company_id):
    _company(db, connection_id, company_id)
    rows = db.execute(
        COMPANY_SCOPE_SQL + '''SELECT i.* FROM valid_items i
        JOIN accessible_items a ON a.id=i.id ORDER BY i.id''',
        _params(connection_id, company_id),
    ).fetchall()
    return [_content_item(db, connection_id, row) for row in rows]


@_transaction
def get_item(db, connection_id, company_id, item_id):
    _company(db, connection_id, company_id)
    return _content_item(db, connection_id, _selected(db, connection_id, company_id, item_id))


@_transaction
def ad_assets(db, connection_id, company_id, ad_item_id):
    _company(db, connection_id, company_id)
    ad = _selected(db, connection_id, company_id, ad_item_id)
    if ad['content_type'] != 'ad':
        raise OwnershipNotFound('Ad was not found.')
    rows = db.execute(
        COMPANY_SCOPE_SQL + '''SELECT asset.* FROM direct_items ad
        JOIN meta_ad_assets edge ON edge.ad_item_id=ad.id
        JOIN valid_items asset ON asset.id=edge.video_item_id
        WHERE ad.id=%(item_id)s AND ad.content_type='ad' AND asset.content_type<>'ad'
        ORDER BY asset.id''',
        _params(connection_id, company_id, item_id=ad_item_id),
    ).fetchall()
    return [_content_item(db, connection_id, row) for row in rows]


@_transaction
def performance(db, connection_id, company_id, item_id):
    _company(db, connection_id, company_id)
    _selected(db, connection_id, company_id, item_id)
    return db.execute(
        COMPANY_SCOPE_SQL + '''SELECT p.item_id,p.snapshot,p.fetched_at,i.content_type,
        CASE WHEN i.content_type<>'ad' THEN 'organic'
             WHEN (SELECT count(*) FROM meta_ad_assets e
                   JOIN valid_items asset ON asset.id=e.video_item_id
                   WHERE e.ad_item_id=i.id AND asset.content_type<>'ad')>1 THEN 'shared_ad'
             ELSE 'ad' END AS attribution
        FROM meta_library_performance p JOIN direct_items i ON i.id=p.item_id
        WHERE i.id=%(item_id)s OR (i.content_type='ad' AND EXISTS (
            SELECT 1 FROM meta_ad_assets e WHERE e.ad_item_id=i.id
            AND e.video_item_id=%(item_id)s
        )) ORDER BY p.item_id''',
        _params(connection_id, company_id, item_id=item_id),
    ).fetchall()


@_transaction
def analysis(db, connection_id, company_id, item_id):
    """Return stored content rows only, never legacy video_performance metrics.

    This is a repository representation, not a new HTTP response contract.
    Analysis belongs to the connection and is reached through the real video FK.
    """
    _company(db, connection_id, company_id)
    item = _selected(db, connection_id, company_id, item_id)
    row = db.execute(
        'SELECT * FROM videos WHERE id=%s AND meta_connection_id=%s',
        (item['video_id'], connection_id),
    ).fetchone()
    if row is None:
        return None
    row.pop('meta_connection_id')
    result = {'video': row}
    for table, ordering in (
        ('transcript_segments', 'segment_index'), ('scenes', 'scene_number'),
        ('on_screen_text', 'detection_index'), ('motion_events', 'event_index'),
    ):
        result[table] = db.execute(
            f'SELECT * FROM {table} WHERE video_id=%s ORDER BY {ordering}',
            (item['video_id'],),
        ).fetchall()
    return result
