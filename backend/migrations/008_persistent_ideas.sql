BEGIN;

-- Prerequisite: migration 006 owns companies(id UUID). No ownership column is
-- added to shared library items; 006's authorization is checked by the service.
CREATE TABLE idea_generation_requests (
    company_id UUID NOT NULL REFERENCES companies(id),
    request_id UUID NOT NULL,
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    claim UUID,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, request_id),
    UNIQUE (company_id, request_id, request_hash),
    CHECK ((claim IS NULL) = (lease_until IS NULL))
);

CREATE TABLE ideas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 300),
    concept TEXT NOT NULL CHECK (length(btrim(concept)) BETWEEN 1 AND 10000),
    script TEXT NOT NULL CHECK (length(btrim(script)) BETWEEN 1 AND 30000),
    generation_brief TEXT CHECK (length(generation_brief) <= 10000),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status = 'draft'),
    recommendation_version INTEGER NOT NULL CHECK (recommendation_version > 0),
    model TEXT NOT NULL CHECK (length(model) > 0),
    evidence_schema_version INTEGER NOT NULL CHECK (evidence_schema_version > 0),
    evidence_captured_at TIMESTAMPTZ NOT NULL,
    request_id UUID NOT NULL,
    request_hash TEXT NOT NULL,
    profile_revision_id UUID,
    profile_evidence JSONB CHECK (jsonb_typeof(profile_evidence) = 'object'),
    prior_idea_evidence JSONB NOT NULL CHECK (jsonb_typeof(prior_idea_evidence) = 'array'),
    evidence_sealed BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, request_id),
    FOREIGN KEY (company_id, request_id, request_hash)
        REFERENCES idea_generation_requests(company_id, request_id, request_hash),
    CHECK ((profile_revision_id IS NULL) = (profile_evidence IS NULL))
);
CREATE INDEX ideas_company_history ON ideas(company_id, created_at DESC, id DESC);

CREATE TABLE idea_sources (
    idea_id UUID NOT NULL REFERENCES ideas(id),
    -- Historical identities intentionally have no FK to mutable/deletable items.
    library_item_id UUID NOT NULL,
    source_order INTEGER NOT NULL CHECK (source_order BETWEEN 0 AND 19),
    analysis_version INTEGER NOT NULL CHECK (analysis_version > 0),
    analysis_payload JSONB NOT NULL CHECK (jsonb_typeof(analysis_payload) = 'object'),
    publication_context JSONB NOT NULL CHECK (jsonb_typeof(publication_context) = 'object'),
    PRIMARY KEY (idea_id, library_item_id),
    UNIQUE (idea_id, source_order)
);
CREATE TABLE idea_performance_evidence (
    idea_id UUID NOT NULL REFERENCES ideas(id),
    library_item_id UUID NOT NULL,
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    fetched_at TIMESTAMPTZ NOT NULL,
    attribution TEXT NOT NULL CHECK (attribution IN ('organic','ad','shared_ad')),
    publication_context JSONB NOT NULL CHECK (jsonb_typeof(publication_context) = 'object'),
    PRIMARY KEY (idea_id, library_item_id)
);
CREATE TABLE idea_source_performance (
    idea_id UUID NOT NULL,
    source_library_item_id UUID NOT NULL,
    performance_library_item_id UUID NOT NULL,
    PRIMARY KEY (idea_id, source_library_item_id, performance_library_item_id),
    FOREIGN KEY (idea_id, source_library_item_id) REFERENCES idea_sources(idea_id, library_item_id),
    FOREIGN KEY (idea_id, performance_library_item_id) REFERENCES idea_performance_evidence(idea_id, library_item_id)
);
CREATE TABLE idea_target_platforms (
    idea_id UUID NOT NULL REFERENCES ideas(id),
    platform TEXT NOT NULL CHECK (platform IN ('instagram','facebook')),
    PRIMARY KEY (idea_id, platform)
);

CREATE FUNCTION guard_idea_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Generation evidence is immutable' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM ideas WHERE id = NEW.idea_id AND NOT evidence_sealed FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Generation evidence is sealed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_sources BEFORE INSERT OR UPDATE OR DELETE ON idea_sources
    FOR EACH ROW EXECUTE FUNCTION guard_idea_evidence();
CREATE TRIGGER immutable_performance BEFORE INSERT OR UPDATE OR DELETE ON idea_performance_evidence
    FOR EACH ROW EXECUTE FUNCTION guard_idea_evidence();
CREATE TRIGGER immutable_mapping BEFORE INSERT OR UPDATE OR DELETE ON idea_source_performance
    FOR EACH ROW EXECUTE FUNCTION guard_idea_evidence();
CREATE TRIGGER immutable_targets BEFORE INSERT OR UPDATE OR DELETE ON idea_target_platforms
    FOR EACH ROW EXECUTE FUNCTION guard_idea_evidence();

CREATE FUNCTION guard_idea_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['title','concept','script','updated_at','evidence_sealed'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['title','concept','script','updated_at','evidence_sealed'])
       OR (OLD.evidence_sealed AND NOT NEW.evidence_sealed) THEN
        RAISE EXCEPTION 'Generation identity and evidence are immutable' USING ERRCODE = '23514';
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_idea_generation BEFORE UPDATE ON ideas
    FOR EACH ROW EXECUTE FUNCTION guard_idea_update();

CREATE FUNCTION check_idea_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n INTEGER; highest INTEGER;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ideas WHERE id=NEW.id AND evidence_sealed) THEN
        RAISE EXCEPTION 'Idea evidence must be sealed before commit' USING ERRCODE = '23514';
    END IF;
    SELECT count(*),max(source_order) INTO n,highest FROM idea_sources WHERE idea_id=NEW.id;
    IF n NOT BETWEEN 1 AND 20 OR highest <> n-1 THEN
        RAISE EXCEPTION 'Idea requires 1-20 ordered sources' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM idea_performance_evidence p WHERE p.idea_id=NEW.id
        AND NOT EXISTS (SELECT 1 FROM idea_source_performance m WHERE m.idea_id=p.idea_id
                        AND m.performance_library_item_id=p.library_item_id)) THEN
        RAISE EXCEPTION 'Performance evidence requires source attribution' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER complete_idea AFTER INSERT ON ideas
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_idea_complete();
COMMIT;
