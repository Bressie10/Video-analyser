BEGIN;

ALTER TABLE meta_library_items ADD COLUMN analysis_stage TEXT
    CHECK (analysis_stage IN ('downloading','inspecting','normalizing','detecting_scenes',
        'reading_text','detecting_motion','extracting_audio','transcribing','saving','complete'));
ALTER TABLE meta_sync_runs DROP CONSTRAINT meta_sync_runs_kind_check;
ALTER TABLE meta_sync_runs ADD CONSTRAINT meta_sync_runs_kind_check
    CHECK (kind IN ('sync','analysis','metrics','bootstrap'));
ALTER TABLE meta_sync_runs ADD COLUMN company_id UUID REFERENCES companies(id);
CREATE TABLE meta_initial_analysis_batches (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES meta_accounts(id) ON DELETE CASCADE,
    run_id UUID NOT NULL UNIQUE REFERENCES meta_sync_runs(id) ON DELETE CASCADE,
    PRIMARY KEY(company_id, account_id)
);
CREATE TABLE meta_initial_analysis_targets (
    run_id UUID NOT NULL REFERENCES meta_sync_runs(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES meta_library_items(id) ON DELETE CASCADE,
    PRIMARY KEY(run_id,item_id)
);

COMMIT;
