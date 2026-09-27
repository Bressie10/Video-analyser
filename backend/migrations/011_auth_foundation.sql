BEGIN;

-- Identity is Supabase Auth's verified sub UUID. No local credentials or guessed
-- ownership. A logical external identity reference keeps standalone PostgreSQL
-- supported; only authenticated server operations may provision these rows.
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE company_memberships (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES user_profiles(user_id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, user_id)
);
CREATE INDEX company_memberships_user ON company_memberships(user_id, company_id);

-- Preserve the connection FK, composite unique key and all dependent FKs.
ALTER TABLE companies ALTER COLUMN connection_id DROP NOT NULL;
ALTER TABLE meta_connections ADD COLUMN owner_user_id UUID
    REFERENCES user_profiles(user_id) ON DELETE RESTRICT;
CREATE INDEX meta_connections_owner ON meta_connections(owner_user_id)
    WHERE owner_user_id IS NOT NULL;

-- No browser table API: default-deny even if Supabase grants table privileges.
-- The backend must connect as table owner or a dedicated BYPASSRLS role.
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_memberships ENABLE ROW LEVEL SECURITY;

COMMIT;
