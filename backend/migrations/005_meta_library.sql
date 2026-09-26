BEGIN;

ALTER TABLE videos ADD COLUMN analysis_version INTEGER NOT NULL DEFAULT 1 CHECK (analysis_version > 0);

CREATE TABLE meta_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_user_id TEXT NOT NULL UNIQUE,
    token_ciphertext TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected','reconnect_required','disconnected')),
    next_sync_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE videos ADD COLUMN meta_connection_id UUID REFERENCES meta_connections(id);
CREATE TABLE meta_sessions (
    token_hash TEXT PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE meta_sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('sync','analysis','metrics')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    discovery_finalized BOOLEAN NOT NULL DEFAULT false,
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX meta_one_sync ON meta_sync_runs(connection_id) WHERE kind='sync' AND finished_at IS NULL;
CREATE TABLE meta_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK (platform IN ('facebook','instagram','meta_ads')),
    external_id TEXT NOT NULL,
    page_external_id TEXT,
    label TEXT NOT NULL,
    timezone_name TEXT NOT NULL DEFAULT 'UTC',
    initialized_at TIMESTAMPTZ,
    initial_run_id UUID REFERENCES meta_sync_runs(id),
    UNIQUE(connection_id,platform,external_id)
);
CREATE TABLE meta_library_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES meta_accounts(id),
    platform TEXT NOT NULL CHECK (platform IN ('facebook','instagram','meta_ads')),
    external_id TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('video','reel','ad')),
    label TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    auto_analyze BOOLEAN NOT NULL DEFAULT false,
    analysis_state TEXT NOT NULL DEFAULT 'discovered' CHECK (analysis_state IN
        ('discovered','deferred','queued','processing','completed','failed','unavailable','unsupported')),
    analysis_error TEXT,
    analysis_version INTEGER,
    video_id UUID REFERENCES videos(id),
    metrics_state TEXT NOT NULL DEFAULT 'pending',
    metrics_error TEXT,
    UNIQUE(connection_id,platform,external_id)
);
CREATE TABLE meta_ad_assets (
    ad_item_id UUID NOT NULL REFERENCES meta_library_items(id) ON DELETE CASCADE,
    video_item_id UUID NOT NULL REFERENCES meta_library_items(id) ON DELETE CASCADE,
    PRIMARY KEY(ad_item_id,video_item_id)
);
CREATE TABLE meta_library_performance (
    item_id UUID PRIMARY KEY REFERENCES meta_library_items(id) ON DELETE CASCADE,
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot)='object'),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE meta_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES meta_sync_runs(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES meta_connections(id) ON DELETE CASCADE,
    item_id UUID REFERENCES meta_library_items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('discovery','analysis','metrics')),
    task_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN
        ('queued','running','completed','reused','failed','unavailable','unsupported','cancelled','blocked')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claim UUID,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id,kind,task_key)
);
CREATE INDEX meta_jobs_ready ON meta_jobs(kind,available_at) WHERE state IN ('queued','running');
CREATE UNIQUE INDEX meta_one_item_task ON meta_jobs(item_id,kind) WHERE state IN ('queued','running','blocked') AND item_id IS NOT NULL;
CREATE INDEX meta_library_connection ON meta_library_items(connection_id,published_at DESC);
COMMIT;
