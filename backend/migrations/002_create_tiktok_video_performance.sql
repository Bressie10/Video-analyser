BEGIN;

CREATE TABLE tiktok_video_performance (
    video_id UUID PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
    view_count BIGINT CHECK (view_count >= 0),
    like_count BIGINT CHECK (like_count >= 0),
    comment_count BIGINT CHECK (comment_count >= 0),
    share_count BIGINT CHECK (share_count >= 0),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(view_count, like_count, comment_count, share_count) > 0)
);

COMMIT;
