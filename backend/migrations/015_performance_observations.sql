BEGIN;

-- Append-only provider observations. Existing video_performance is untouched.
CREATE TABLE performance_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL,
    connection_id UUID,
    account_uuid UUID,
    item_uuid UUID,
    video_id UUID,
    source TEXT NOT NULL CHECK (source IN ('meta_ads','facebook','instagram','tiktok')),
    provider_object_type TEXT NOT NULL CHECK (provider_object_type IN ('ad','video','reel')),
    provider_object_id TEXT NOT NULL CHECK (btrim(provider_object_id) <> ''),
    provider_account_id TEXT NOT NULL CHECK (btrim(provider_account_id) <> ''),
    placement_scope TEXT NOT NULL CHECK (btrim(placement_scope) <> ''),
    exposure_type TEXT NOT NULL CHECK (exposure_type IN ('paid','organic')),
    report_start DATE,
    report_end DATE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    account_currency TEXT CHECK (account_currency ~ '^[A-Z]{3}$'),
    action_report_time TEXT,
    attribution_windows TEXT[] NOT NULL DEFAULT '{}',
    metric_payload JSONB NOT NULL CHECK (jsonb_typeof(metric_payload)='object'),
    provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance)='object'),
    context_key TEXT NOT NULL CHECK (context_key ~ '^[0-9a-f]{64}$'),
    CHECK ((report_start IS NULL AND report_end IS NULL) OR
           (report_start IS NOT NULL AND report_end IS NOT NULL AND report_start<=report_end)),
    CHECK ((source='meta_ads' AND exposure_type='paid') OR
           (source<>'meta_ads' AND exposure_type='organic')),
    CHECK (source<>'meta_ads' OR (connection_id IS NOT NULL AND account_uuid IS NOT NULL
          AND item_uuid IS NOT NULL AND provider_object_type='ad' AND exposure_type='paid'
          AND placement_scope='meta_all_placements' AND report_start IS NOT NULL
          AND account_currency IS NOT NULL AND action_report_time='impression'
          AND attribution_windows=ARRAY['7d_click','1d_view']::TEXT[])),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT,
    FOREIGN KEY (company_id,connection_id) REFERENCES companies(id,connection_id) ON DELETE RESTRICT,
    FOREIGN KEY (account_uuid) REFERENCES meta_accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY (account_uuid,connection_id) REFERENCES meta_accounts(id,connection_id) ON DELETE RESTRICT,
    FOREIGN KEY (item_uuid) REFERENCES meta_library_items(id) ON DELETE RESTRICT,
    FOREIGN KEY (item_uuid,connection_id,account_uuid,provider_object_type)
        REFERENCES meta_library_items(id,connection_id,account_id,content_type) ON DELETE RESTRICT,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE RESTRICT,
    FOREIGN KEY (video_id,connection_id) REFERENCES videos(id,meta_connection_id) ON DELETE RESTRICT
);

ALTER TABLE performance_observations ENABLE ROW LEVEL SECURITY;

CREATE INDEX performance_observations_cohort ON performance_observations
    (company_id,source,provider_account_id,placement_scope,report_start,report_end,
     action_report_time,context_key,fetched_at DESC,id);
CREATE INDEX performance_observations_object ON performance_observations
    (company_id,source,provider_object_id,fetched_at DESC,id);

CREATE FUNCTION reject_performance_observation_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Performance observations are immutable';
END;
$$;
CREATE TRIGGER performance_observations_immutable
    BEFORE UPDATE OR DELETE ON performance_observations
    FOR EACH ROW EXECUTE FUNCTION reject_performance_observation_mutation();

CREATE FUNCTION validate_performance_observation_link() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source <> 'meta_ads' THEN
        RAISE EXCEPTION 'Organic observation writer is not enabled';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM company_accounts ca JOIN meta_accounts a
          ON a.id=ca.account_id AND a.connection_id=ca.connection_id
        JOIN meta_library_items i ON i.id=NEW.item_uuid AND i.account_id=a.id
          AND i.connection_id=a.connection_id
        WHERE ca.company_id=NEW.company_id AND ca.connection_id=NEW.connection_id
          AND ca.account_id=NEW.account_uuid
          AND a.external_id=NEW.provider_account_id
          AND i.external_id=NEW.provider_object_id
          AND i.content_type=NEW.provider_object_type
          AND i.video_id IS NOT DISTINCT FROM NEW.video_id
          AND ca.account_platform='meta_ads'
          AND EXISTS (SELECT 1 FROM company_ad_assignments x
                   WHERE x.ad_item_id=i.id AND x.company_id=NEW.company_id
                     AND x.connection_id=NEW.connection_id AND x.account_id=NEW.account_uuid)
    ) THEN
        RAISE EXCEPTION 'Observation ownership or provider identity mismatch';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER performance_observations_validate_link
    BEFORE INSERT ON performance_observations
    FOR EACH ROW EXECUTE FUNCTION validate_performance_observation_link();

COMMIT;
