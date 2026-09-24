BEGIN;

DO $$
DECLARE
    test_video_id UUID := gen_random_uuid();
BEGIN
    INSERT INTO videos (
        id, duration_seconds, container, file_size_bytes, overall_bit_rate,
        video_codec, video_codec_long_name, width, height, fps, source_fps,
        pixel_format, video_bit_rate, frame_count, audio_codec,
        audio_codec_long_name, audio_sample_rate, audio_channels,
        audio_channel_layout, audio_bit_rate, transcript_text
    ) VALUES (
        test_video_id, 12.345, 'mov,mp4', 1234567, 800000,
        'h264', 'H.264 / AVC', 1920, 1080, 29.970, 30.000,
        'yuv420p', 700000, 370, 'aac',
        'AAC', 48000, 2, 'stereo', 96000, 'Hello world'
    );

    INSERT INTO transcript_segments (video_id, segment_index, start_seconds, end_seconds, text)
    VALUES (test_video_id, 0, 0.100, 1.250, 'Hello world');

    INSERT INTO scenes (
        video_id, scene_number, start_seconds, end_seconds,
        duration_seconds, cut_timestamp_seconds
    ) VALUES (test_video_id, 1, 0.000, 5.000, 5.000, NULL),
             (test_video_id, 2, 5.000, 12.345, 7.345, 5.000);

    INSERT INTO on_screen_text (
        video_id, detection_index, text, bounding_box, confidence,
        appearance_timestamp_seconds, disappearance_timestamp_seconds
    ) VALUES (
        test_video_id, 0, 'Watch this', '[[10,20],[110,20],[110,50],[10,50]]',
        0.987, 1.500, 3.000
    );

    INSERT INTO motion_events (
        video_id, event_index, start_seconds, end_seconds, type, confidence
    ) VALUES (test_video_id, 0, 2.000, 4.250, 'camera_pan', 0.875);

    INSERT INTO tiktok_video_performance
        (video_id, view_count, like_count, comment_count, share_count)
    VALUES (test_video_id, 120, 12, 3, 2);

    IF NOT EXISTS (
        SELECT 1 FROM videos
        WHERE id = test_video_id
          AND aspect_ratio = 1920::NUMERIC / 1080
          AND duration_seconds = 12.345
          AND container = 'mov,mp4'
          AND file_size_bytes = 1234567
          AND overall_bit_rate = 800000
          AND video_codec = 'h264'
          AND video_codec_long_name = 'H.264 / AVC'
          AND width = 1920 AND height = 1080
          AND fps = 29.970 AND source_fps = 30.000
          AND pixel_format = 'yuv420p' AND video_bit_rate = 700000
          AND frame_count = 370 AND audio_codec = 'aac'
          AND audio_codec_long_name = 'AAC' AND audio_sample_rate = 48000
          AND audio_channels = 2 AND audio_channel_layout = 'stereo'
          AND audio_bit_rate = 96000 AND transcript_text = 'Hello world'
    ) THEN
        RAISE EXCEPTION 'video metadata did not round-trip';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM transcript_segments
        WHERE video_id = test_video_id AND segment_index = 0
          AND start_seconds = 0.100 AND end_seconds = 1.250
          AND text = 'Hello world'
    ) OR NOT EXISTS (
        SELECT 1 FROM scenes
        WHERE video_id = test_video_id AND scene_number = 2
          AND start_seconds = 5.000 AND end_seconds = 12.345
          AND duration_seconds = 7.345 AND cut_timestamp_seconds = 5.000
    ) OR NOT EXISTS (
        SELECT 1 FROM on_screen_text
        WHERE video_id = test_video_id AND detection_index = 0
          AND text = 'Watch this'
          AND bounding_box = '[[10,20],[110,20],[110,50],[10,50]]'::JSONB
          AND confidence = 0.987
          AND appearance_timestamp_seconds = 1.500
          AND disappearance_timestamp_seconds = 3.000
    ) OR NOT EXISTS (
        SELECT 1 FROM motion_events
        WHERE video_id = test_video_id AND event_index = 0
          AND start_seconds = 2.000 AND end_seconds = 4.250
          AND type = 'camera_pan' AND confidence = 0.875
    ) THEN
        RAISE EXCEPTION 'analysis data did not round-trip';
    END IF;

    IF (SELECT count(*) FROM scenes WHERE video_id = test_video_id) <> 2
       OR NOT EXISTS (
           SELECT 1 FROM scenes
           WHERE video_id = test_video_id AND scene_number = 1
             AND cut_timestamp_seconds IS NULL
       ) THEN
        RAISE EXCEPTION 'scene order or first-scene cut was lost';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM tiktok_video_performance
        WHERE video_id = test_video_id AND view_count = 120
          AND like_count = 12 AND comment_count = 3 AND share_count = 2
    ) THEN
        RAISE EXCEPTION 'TikTok performance data did not round-trip';
    END IF;
END $$;

ROLLBACK;
