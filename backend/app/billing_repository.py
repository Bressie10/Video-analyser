"""Company billing periods and immutable, transaction-scoped usage accounting."""

from calendar import monthrange
from datetime import datetime, timedelta, timezone


LIMITS = {
    'free': {'organic_account_limit': 1, 'analysis_limit': 3, 'idea_generation_limit': 5},
    'pro': {'organic_account_limit': 5, 'analysis_limit': 50, 'idea_generation_limit': 150},
}
GRACE = timedelta(days=3)


def next_month(start):
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))


def initialize(db, company_id, *, at=None):
    """Serialize period changes and reservations on the company billing row."""
    at = at or datetime.now(timezone.utc)
    db.execute('''INSERT INTO company_billing(company_id,current_period_start,current_period_end)
        VALUES (%s,%s,%s) ON CONFLICT (company_id) DO NOTHING''',
        (company_id, at, next_month(at)))
    row = db.execute('SELECT * FROM company_billing WHERE company_id=%s FOR UPDATE',
                     (company_id,)).fetchone()
    if row['plan_code'] == 'pro':
        downgrade_at = None
        if row['subscription_status'] == 'past_due' and row['grace_until'] and at >= row['grace_until']:
            downgrade_at = row['grace_until']
        elif (row['subscription_status'] == 'past_due' and row['grace_until']
              and at >= row['current_period_end']):
            # Grace can outlast the mirrored paid period. Keep one bounded,
            # meterable Pro interval until the already persisted grace deadline.
            row = db.execute('''UPDATE company_billing SET current_period_start=%s,
                current_period_end=%s,updated_at=now() WHERE company_id=%s RETURNING *''',
                (row['current_period_end'], row['grace_until'], company_id)).fetchone()
        elif row['subscription_status'] in ('active', 'trialing', 'canceled') and at >= row['current_period_end']:
            downgrade_at = row['current_period_end']
        if downgrade_at is not None:
            row = start_free(db, row, at=downgrade_at)
    if row['plan_code'] == 'free' and at >= row['current_period_end']:
        start = row['current_period_end']
        while next_month(start) <= at:
            start = next_month(start)
        end = next_month(start)
        row = db.execute('''UPDATE company_billing SET current_period_start=%s,
            current_period_end=%s, updated_at=now() WHERE company_id=%s RETURNING *''',
            (start, end, company_id)).fetchone()
    return row


def effective_plan(row, *, at=None):
    at = at or datetime.now(timezone.utc)
    status = row['subscription_status']
    if row['plan_code'] != 'pro':
        return 'free'
    if status in ('active', 'trialing') and at < row['current_period_end']:
        return 'pro'
    if status == 'past_due' and row['grace_until'] and at < row['grace_until']:
        return 'pro'
    if status == 'canceled' and at < row['current_period_end']:
        return 'pro'
    return 'free'


def usage(db, row):
    rows = db.execute('''SELECT usage_kind,COALESCE(sum(delta),0)::integer AS used
        FROM company_usage_ledger WHERE company_id=%s
        AND occurred_at >= %s AND occurred_at < %s GROUP BY usage_kind''',
        (row['company_id'], row['current_period_start'], row['current_period_end'])).fetchall()
    values = {r['usage_kind']: r['used'] for r in rows}
    return {'analyses': values.get('analysis', 0), 'idea_generations': values.get('idea_generation', 0)}


def snapshot(db, row, *, can_manage_billing, at=None):
    plan = effective_plan(row, at=at)
    return {
        'plan': row['plan_code'], 'effective_plan': plan,
        'subscription_status': row['subscription_status'],
        'cancel_at_period_end': row['cancel_at_period_end'],
        'grace_until': row['grace_until'], 'entitlements': LIMITS[plan],
        'usage': usage(db, row),
        'period': {'starts_at': row['current_period_start'], 'ends_at': row['current_period_end']},
        'can_manage_billing': can_manage_billing,
    }


def record_usage(db, company_id, kind, delta, key, source_type, source_identifier, reason, *, at=None):
    """Call inside a transaction after company authorization. Locks serialize callers.

    A replay returns the original row only if all immutable claims match. A key
    reused for another company/operation is an error rather than a silent credit.
    """
    if kind not in ('analysis', 'idea_generation') or delta not in (-1, 1):
        raise ValueError('Invalid usage event.')
    row = initialize(db, company_id, at=at)
    event = db.execute('''INSERT INTO company_usage_ledger
        (company_id,usage_kind,delta,idempotency_key,source_type,source_identifier,reason,occurred_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (idempotency_key) DO NOTHING RETURNING *''',
        (company_id, kind, delta, key, source_type, source_identifier, reason,
         at or datetime.now(timezone.utc))).fetchone()
    if event is None:
        event = db.execute('SELECT * FROM company_usage_ledger WHERE idempotency_key=%s', (key,)).fetchone()
        if any(event[field] != value for field, value in {
            'company_id': company_id, 'usage_kind': kind, 'delta': delta,
            'source_type': source_type, 'source_identifier': source_identifier,
            'reason': reason,
        }.items()):
            raise ValueError('Usage idempotency key collision.')
    return event


def start_free(db, row, *, at, status=None, subscription_id=None):
    return db.execute('''UPDATE company_billing SET plan_code='free',
        stripe_subscription_id=COALESCE(%s,stripe_subscription_id),subscription_status=%s,
        current_period_start=%s,current_period_end=%s,
        cancel_at_period_end=false,updated_at=now()
        WHERE company_id=%s RETURNING *''',
        (subscription_id, status or row['subscription_status'], at, next_month(at),
         row['company_id'])).fetchone()


def apply_subscription(db, row, subscription, *, price_id, at=None):
    """Mirror only the configured Price and this company's mapped customer."""
    at = at or datetime.now(timezone.utc)
    if subscription.get('customer') != row['stripe_customer_id']:
        raise ValueError('Subscription customer mismatch.')
    items = subscription.get('items', {}).get('data', [])
    matching = [item for item in items if item.get('price', {}).get('id') == price_id]
    if len(items) != 1 or len(matching) != 1 or matching[0].get('quantity', 1) != 1:
        raise ValueError('Unexpected subscription price or quantity.')
    status = subscription.get('status')
    if status not in ('active','trialing','past_due','canceled','incomplete','incomplete_expired','unpaid'):
        raise ValueError('Unknown subscription status.')
    item = matching[0]
    start = datetime.fromtimestamp(item['current_period_start'], timezone.utc)
    end = datetime.fromtimestamp(item['current_period_end'], timezone.utc)
    if end <= start:
        raise ValueError('Invalid subscription period.')
    if row['plan_code'] == 'free' and row['stripe_subscription_id'] == subscription['id']:
        if status in ('canceled', 'incomplete', 'unpaid', 'incomplete_expired') or (
            status == 'past_due' and row['grace_until'] and at >= row['grace_until']
        ):
            return row
    existing = row['stripe_subscription_id']
    if existing and existing != subscription['id'] and effective_plan(row, at=at) == 'pro':
        raise ValueError('Company already has a paid subscription.')
    grace = row['grace_until'] if status == 'past_due' and existing == subscription['id'] else None
    if status == 'past_due' and grace is None:
        grace = at + GRACE
    if status in ('incomplete','unpaid','incomplete_expired') or (status == 'canceled' and at >= end):
        return start_free(db, row, at=at, status=status, subscription_id=subscription['id'])
    return db.execute('''UPDATE company_billing SET plan_code='pro',stripe_subscription_id=%s,
        subscription_status=%s,current_period_start=%s,current_period_end=%s,
        cancel_at_period_end=%s,grace_until=%s,updated_at=now()
        WHERE company_id=%s RETURNING *''',
        (subscription['id'], status, start, end, bool(subscription.get('cancel_at_period_end')),
         grace, row['company_id'])).fetchone()
