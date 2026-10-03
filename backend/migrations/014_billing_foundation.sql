BEGIN;

CREATE TABLE company_billing (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE RESTRICT,
    plan_code TEXT NOT NULL DEFAULT 'free' CHECK (plan_code IN ('free','pro')),
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    subscription_status TEXT CHECK (subscription_status IN
        ('active','trialing','past_due','canceled','incomplete','incomplete_expired','unpaid')),
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT false,
    grace_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (current_period_end > current_period_start),
    CHECK (stripe_subscription_id IS NULL OR stripe_customer_id IS NOT NULL),
    CHECK (subscription_status IS NULL OR stripe_subscription_id IS NOT NULL),
    CHECK (stripe_customer_id IS NULL OR stripe_customer_id ~ '^cus_[A-Za-z0-9]+$'),
    CHECK (stripe_subscription_id IS NULL OR stripe_subscription_id ~ '^sub_[A-Za-z0-9]+$')
);

CREATE TABLE company_usage_ledger (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    usage_kind TEXT NOT NULL CHECK (usage_kind IN ('analysis','idea_generation')),
    delta INTEGER NOT NULL CHECK (delta IN (-1,1)),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 1 AND 255),
    source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 80),
    source_identifier TEXT NOT NULL CHECK (length(source_identifier) BETWEEN 1 AND 255),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 255),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX company_usage_period ON company_usage_ledger(company_id,usage_kind,occurred_at);

-- The database prevents changes to accounting history, including by the table owner.
CREATE FUNCTION reject_usage_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage ledger is append only';
END $$;
CREATE TRIGGER usage_ledger_immutable BEFORE UPDATE OR DELETE ON company_usage_ledger
    FOR EACH ROW EXECUTE FUNCTION reject_usage_ledger_mutation();

CREATE TABLE stripe_webhook_events (
    event_id TEXT PRIMARY KEY CHECK (event_id ~ '^evt_[A-Za-z0-9]+$'),
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE company_billing ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE stripe_webhook_events ENABLE ROW LEVEL SECURITY;

COMMIT;
