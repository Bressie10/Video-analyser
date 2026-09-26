BEGIN;

-- Preserve the existing snapshot, timestamp, constraints, and video relationship.
ALTER TABLE tiktok_video_performance RENAME TO video_performance;
ALTER TABLE video_performance
    ADD COLUMN source TEXT NOT NULL DEFAULT 'tiktok'
    CHECK (source IN ('tiktok', 'instagram', 'facebook', 'meta_ads'));
-- Backfill old rows only; future writers must supply their source explicitly.
ALTER TABLE video_performance ALTER COLUMN source DROP DEFAULT;

COMMIT;
