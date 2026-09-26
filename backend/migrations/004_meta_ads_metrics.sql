BEGIN;

-- Decimal amounts/rates and action breakdowns cannot fit the four BIGINT counts.
ALTER TABLE video_performance ADD COLUMN meta_ads JSONB;
ALTER TABLE video_performance ADD CONSTRAINT video_performance_meta_ads_source_check
    CHECK (meta_ads IS NULL OR (source = 'meta_ads' AND jsonb_typeof(meta_ads) = 'object'));
ALTER TABLE video_performance DROP CONSTRAINT tiktok_video_performance_check;
ALTER TABLE video_performance ADD CONSTRAINT video_performance_has_metrics_check CHECK (
    num_nonnulls(view_count, like_count, comment_count, share_count) > 0 OR
    (meta_ads IS NOT NULL AND (
        COALESCE(meta_ads->>'impressions', meta_ads->>'reach', meta_ads->>'clicks',
                 meta_ads->>'spend', meta_ads->>'ctr', meta_ads->>'cpc') IS NOT NULL OR
        jsonb_path_exists(meta_ads, '$.actions[*].value ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.conversions[*].value ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.video_play_actions[*].value ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.actions[*]."7d_click" ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.actions[*]."1d_view" ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.conversions[*]."7d_click" ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.conversions[*]."1d_view" ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.video_play_actions[*]."7d_click" ? (@ != null)') OR
        jsonb_path_exists(meta_ads, '$.video_play_actions[*]."1d_view" ? (@ != null)')
    ))
);

COMMIT;
