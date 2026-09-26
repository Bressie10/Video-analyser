BEGIN;

-- 006 owns companies and access. This migration intentionally requires it.
CREATE TABLE company_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),
    scope TEXT NOT NULL CHECK (scope IN ('shared','instagram','facebook','meta_ads')),
    current_revision_id UUID,
    input_revision BIGINT NOT NULL DEFAULT 1 CHECK (input_revision > 0),
    validated_input_revision BIGINT NOT NULL DEFAULT 0,
    generator_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    suppressed BOOLEAN NOT NULL DEFAULT false,
    invalidation_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(company_id,scope)
);
CREATE TABLE company_profile_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES company_profiles(id),
    revision_number BIGINT NOT NULL CHECK (revision_number > 0),
    input_revision BIGINT NOT NULL,
    input_hash TEXT NOT NULL,
    assignment_version TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    model TEXT NOT NULL,
    document JSONB NOT NULL CHECK (jsonb_typeof(document)='object'),
    evidence_manifest JSONB NOT NULL CHECK (jsonb_typeof(evidence_manifest)='object'),
    dependencies JSONB NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(dependencies)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(profile_id,revision_number),
    UNIQUE(profile_id,id)
);
ALTER TABLE company_profiles ADD CONSTRAINT company_profile_current_revision
    FOREIGN KEY (id,current_revision_id) REFERENCES company_profile_revisions(profile_id,id);
CREATE FUNCTION company_profile_revision_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Successful company profile revisions are immutable';
END;
$$;
CREATE TRIGGER company_profile_revision_immutable BEFORE UPDATE OR DELETE
    ON company_profile_revisions FOR EACH ROW EXECUTE FUNCTION company_profile_revision_immutable();

CREATE TABLE company_profile_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES company_profiles(id),
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','completed','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claim UUID,
    captured_input_revision BIGINT,
    input_hash TEXT,
    outcome TEXT CHECK (outcome IN ('generated','reused','superseded')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX company_profile_one_active ON company_profile_jobs(profile_id)
    WHERE state IN ('queued','running');
CREATE INDEX company_profile_jobs_ready ON company_profile_jobs(available_at,created_at)
    WHERE state IN ('queued','running');
CREATE TABLE company_profile_refresh_requests (
    profile_id UUID NOT NULL REFERENCES company_profiles(id),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    job_id UUID NOT NULL REFERENCES company_profile_jobs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(profile_id,idempotency_key)
);
CREATE TABLE company_profile_invalidations (
    company_id UUID NOT NULL REFERENCES companies(id),
    event_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(company_id,event_key)
);
-- Bound candidate lookup by the company adapter's assigned accounts.
CREATE INDEX company_profile_evidence_candidates ON meta_library_items(account_id,platform,published_at DESC,id);
COMMIT;
