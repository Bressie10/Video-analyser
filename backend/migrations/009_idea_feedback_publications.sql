BEGIN;

ALTER TABLE ideas DROP CONSTRAINT ideas_status_check;
ALTER TABLE ideas ADD CONSTRAINT ideas_status_check
    CHECK (status IN ('draft','used','published','discarded'));
ALTER TABLE ideas ADD COLUMN feedback TEXT NOT NULL DEFAULT 'none'
    CHECK (feedback IN ('none','liked','disliked'));
ALTER TABLE ideas ADD COLUMN feedback_reason TEXT
    CONSTRAINT ideas_feedback_reason_length CHECK (length(feedback_reason) <= 2000);
ALTER TABLE ideas ADD CONSTRAINT ideas_feedback_reason_check
    CHECK (feedback = 'disliked' OR feedback_reason IS NULL);

-- Extend the mutable current-state allowlist; generation evidence stays sealed.
CREATE OR REPLACE FUNCTION guard_idea_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['title','concept','script','status','feedback','feedback_reason',
                             'updated_at','evidence_sealed'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['title','concept','script','status','feedback','feedback_reason',
                             'updated_at','evidence_sealed'])
       OR (OLD.evidence_sealed AND NOT NEW.evidence_sealed) THEN
        RAISE EXCEPTION 'Generation identity and evidence are immutable' USING ERRCODE = '23514';
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

-- Company identity comes only from the idea's immutable company_id. No FK to
-- mutable company account/ad assignments: unlink/reassignment retains history.
-- Explicit RESTRICT avoids destroying history through library/idea deletion.
CREATE TABLE idea_publications (
    idea_id UUID NOT NULL REFERENCES ideas(id) ON DELETE RESTRICT,
    library_item_id UUID NOT NULL REFERENCES meta_library_items(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (idea_id, library_item_id)
);
CREATE INDEX idea_publications_library_item ON idea_publications(library_item_id);

-- ideas_company_history already bounds recent company feedback/history reads.
COMMIT;
