"""Company entitlements and append-only, serialized usage decisions."""

from datetime import datetime, timezone

from fastapi import HTTPException

from app import billing_repository as billing


LIMIT_CODES = {
    'analysis': 'analysis_limit_reached',
    'idea_generation': 'idea_generation_limit_reached',
}


def limit_error(code):
    return HTTPException(402, {'code': code, 'message': 'Plan limit reached.'})


def reserve_usage(db, company_id, kind, key, source_type, source_id):
    """Call in the durable operation's transaction, after company authorization.

    The billing row serializes the sum and insert. Replays are checked before the
    limit so a completed operation remains readable after its quota is full.
    """
    if kind not in LIMIT_CODES:
        raise ValueError('Invalid usage kind.')
    # Take the decision timestamp after acquiring the row lock. A contender
    # waiting across a period boundary must be evaluated in the new period.
    billing.initialize(db, company_id)
    at = datetime.now(timezone.utc)
    row = billing.initialize(db, company_id, at=at)
    existing = db.execute('SELECT * FROM company_usage_ledger WHERE idempotency_key=%s',
                          (key,)).fetchone()
    if existing:
        if any(existing[field] != value for field, value in {
            'company_id': company_id, 'usage_kind': kind, 'delta': 1,
            'source_type': source_type, 'source_identifier': str(source_id),
            'reason': 'reserve',
        }.items()):
            raise ValueError('Usage idempotency key collision.')
        return billing.snapshot(db, row, can_manage_billing=False, at=at)
    used = billing.usage(db, row)
    field = 'analyses' if kind == 'analysis' else 'idea_generations'
    limit = billing.LIMITS[billing.effective_plan(row, at=at)][kind + '_limit']
    if used[field] >= limit:
        raise limit_error(LIMIT_CODES[kind])
    billing.record_usage(db, company_id, kind, 1, key, source_type, str(source_id),
                         'reserve', at=at)
    return billing.snapshot(db, row, can_manage_billing=False, at=at)


def refund_usage(db, company_id, kind, reserve_key, refund_key, source_type, source_id):
    """Append one reversal in the original period; never credit an absent debit."""
    row = billing.initialize(db, company_id)
    reserve = db.execute('SELECT * FROM company_usage_ledger WHERE idempotency_key=%s',
                         (reserve_key,)).fetchone()
    if reserve is None:
        return billing.snapshot(db, row, can_manage_billing=False)
    if any(reserve[field] != value for field, value in {
        'company_id': company_id, 'usage_kind': kind, 'delta': 1,
        'source_type': source_type, 'source_identifier': str(source_id), 'reason': 'reserve',
    }.items()):
        raise ValueError('Usage reservation mismatch.')
    billing.record_usage(db, company_id, kind, -1, refund_key, source_type,
                         str(source_id), 'refund', at=reserve['occurred_at'])
    return billing.snapshot(db, row, can_manage_billing=False)


def require_organic_slot(db, company_id, account_id):
    """Caller holds the company write lock and performs link in this transaction."""
    account = db.execute('SELECT platform FROM meta_accounts WHERE id=%s', (account_id,)).fetchone()
    if account is None or account['platform'] not in ('facebook', 'instagram'):
        return
    if db.execute('SELECT 1 FROM company_accounts WHERE company_id=%s AND account_id=%s',
                  (company_id, account_id)).fetchone():
        return
    row = billing.initialize(db, company_id)
    count = db.execute('''SELECT count(*) AS n FROM company_accounts
        WHERE company_id=%s AND account_platform IN ('facebook','instagram')''',
        (company_id,)).fetchone()['n']
    if count >= billing.LIMITS[billing.effective_plan(row)]['organic_account_limit']:
        raise limit_error('organic_account_limit_reached')


def require_free_workspace_slot(db, user_id):
    """Serialize prospective creation per verified owner, even for zero companies."""
    db.execute('INSERT INTO user_profiles(user_id) VALUES (%s) ON CONFLICT DO NOTHING',
               (user_id,))
    db.execute('SELECT user_id FROM user_profiles WHERE user_id=%s FOR UPDATE',
               (user_id,)).fetchone()
    owned = db.execute('''SELECT c.id FROM companies c JOIN company_memberships m
        ON m.company_id=c.id WHERE m.user_id=%s AND m.role='owner' ORDER BY c.id''',
        (user_id,)).fetchall()
    for item in owned:
        if billing.effective_plan(billing.initialize(db, item['id'])) == 'free':
            raise limit_error('free_workspace_limit_reached')
