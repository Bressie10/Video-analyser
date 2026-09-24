BEGIN;

CREATE TABLE videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    duration_seconds NUMERIC(12, 3) NOT NULL CHECK (duration_seconds > 0),
    container TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes >= 0),
    overall_bit_rate BIGINT CHECK (overall_bit_rate >= 0),
    video_codec TEXT,
    video_codec_long_name TEXT,
    width INTEGER CHECK (width > 0),
    height INTEGER CHECK (height > 0),
    aspect_ratio NUMERIC GENERATED ALWAYS AS (width::NUMERIC / NULLIF(height, 0)) STORED,
    fps NUMERIC(12, 3) CHECK (fps >= 0),
    source_fps NUMERIC(12, 3) CHECK (source_fps >= 0),
    pixel_format TEXT,
    video_bit_rate BIGINT CHECK (video_bit_rate >= 0),
    frame_count BIGINT CHECK (frame_count >= 0),
    audio_codec TEXT,
    audio_codec_long_name TEXT,
    audio_sample_rate INTEGER CHECK (audio_sample_rate > 0),
    audio_channels INTEGER CHECK (audio_channels > 0),
    audio_channel_layout TEXT,
    audio_bit_rate BIGINT CHECK (audio_bit_rate >= 0),
    transcript_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE transcript_segments (
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL CHECK (segment_index >= 0),
    start_seconds NUMERIC(12, 3) NOT NULL CHECK (start_seconds >= 0),
    end_seconds NUMERIC(12, 3) NOT NULL CHECK (end_seconds >= start_seconds),
    text TEXT NOT NULL,
    PRIMARY KEY (video_id, segment_index)
);

CREATE TABLE scenes (
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    scene_number INTEGER NOT NULL CHECK (scene_number > 0),
    start_seconds NUMERIC(12, 3) NOT NULL CHECK (start_seconds >= 0),
    end_seconds NUMERIC(12, 3) NOT NULL CHECK (end_seconds >= start_seconds),
    duration_seconds NUMERIC(12, 3) NOT NULL CHECK (duration_seconds >= 0),
    cut_timestamp_seconds NUMERIC(12, 3) CHECK (cut_timestamp_seconds >= 0),
    PRIMARY KEY (video_id, scene_number)
);

CREATE TABLE on_screen_text (
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    detection_index INTEGER NOT NULL CHECK (detection_index >= 0),
    text TEXT NOT NULL,
    bounding_box JSONB NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    appearance_timestamp_seconds NUMERIC(12, 3) NOT NULL
        CHECK (appearance_timestamp_seconds >= 0),
    disappearance_timestamp_seconds NUMERIC(12, 3) NOT NULL
        CHECK (disappearance_timestamp_seconds >= appearance_timestamp_seconds),
    PRIMARY KEY (video_id, detection_index)
);

CREATE TABLE motion_events (
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    event_index INTEGER NOT NULL CHECK (event_index >= 0),
    start_seconds NUMERIC(12, 3) NOT NULL CHECK (start_seconds >= 0),
    end_seconds NUMERIC(12, 3) NOT NULL CHECK (end_seconds >= start_seconds),
    type TEXT NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (video_id, event_index)
);

COMMIT;
