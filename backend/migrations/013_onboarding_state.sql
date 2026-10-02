BEGIN;

-- Supabase identity is a logical UUID reference through user_profiles, as in 011.
CREATE TABLE user_onboarding_state (
    user_id UUID PRIMARY KEY REFERENCES user_profiles(user_id) ON DELETE CASCADE,
    onboarding_company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    welcome_seen_at TIMESTAMPTZ,
    onboarding_skipped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Browser Data API access is denied; FastAPI uses the table owner/BYPASSRLS role.
ALTER TABLE user_onboarding_state ENABLE ROW LEVEL SECURITY;

COMMIT;
