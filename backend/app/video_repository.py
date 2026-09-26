"""PostgreSQL access to processed video data."""

import os
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.performance import performance_snapshot


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("Database is not configured.")
    return database_url


def save_analysis(analysis: dict) -> str:
    """Store one processing result and its ordered child records atomically."""
    performance = None
    if analysis.get("performance_metrics") is not None:
        performance = performance_snapshot(analysis["performance_source"], analysis["performance_metrics"])
    metadata = analysis["metadata"]
    video = metadata["video"]
    audio = metadata["audio"]
    with psycopg.connect(_database_url(), connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO videos (
                    duration_seconds, container, file_size_bytes, overall_bit_rate,
                    video_codec, video_codec_long_name, width, height, fps, source_fps,
                    pixel_format, video_bit_rate, frame_count, audio_codec,
                    audio_codec_long_name, audio_sample_rate, audio_channels,
                    audio_channel_layout, audio_bit_rate, transcript_text
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id""",
                (
                    metadata["duration_seconds"], metadata["container"],
                    metadata["file_size_bytes"], metadata["overall_bit_rate"],
                    video["codec"], video["codec_long_name"],
                    video["resolution"]["width"], video["resolution"]["height"],
                    video["fps"], video["source_fps"], video["pixel_format"],
                    video["bit_rate"], video["frame_count"], audio["codec"],
                    audio["codec_long_name"], audio["sample_rate"],
                    audio["channels"], audio["channel_layout"], audio["bit_rate"],
                    analysis["audio"]["text"],
                ),
            )
            video_id = cursor.fetchone()[0]
            for index, segment in enumerate(analysis["audio"]["segments"]):
                cursor.execute(
                    """INSERT INTO transcript_segments
                    (video_id, segment_index, start_seconds, end_seconds, text)
                    VALUES (%s, %s, %s, %s, %s)""",
                    (video_id, index, segment["start"], segment["end"], segment["text"]),
                )
            for scene in analysis["scenes"]:
                cursor.execute(
                    """INSERT INTO scenes (video_id, scene_number, start_seconds,
                    end_seconds, duration_seconds, cut_timestamp_seconds)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (video_id, scene["scene_number"], scene["start_seconds"],
                     scene["end_seconds"], scene["duration_seconds"],
                     scene["cut_timestamp_seconds"]),
                )
            for index, detection in enumerate(analysis["on_screen_text"]):
                cursor.execute(
                    """INSERT INTO on_screen_text (video_id, detection_index, text,
                    bounding_box, confidence, appearance_timestamp_seconds,
                    disappearance_timestamp_seconds)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (video_id, index, detection["text"], Jsonb(detection["bounding_box"]),
                     detection["confidence"], detection["appearance_timestamp_seconds"],
                     detection["disappearance_timestamp_seconds"]),
                )
            for index, event in enumerate(analysis["motion_events"]):
                cursor.execute(
                    """INSERT INTO motion_events (video_id, event_index, start_seconds,
                    end_seconds, type, confidence) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (video_id, index, event["start_seconds"], event["end_seconds"],
                     event["type"], event["confidence"]),
                )
            if performance is not None:
                counts = performance["performance_metrics"]
                cursor.execute(
                    """INSERT INTO video_performance
                    (video_id, source, view_count, like_count, comment_count, share_count)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (video_id, performance["performance_source"], counts["view_count"], counts["like_count"],
                     counts["comment_count"], counts["share_count"]),
                )
    return str(video_id)


def get_analysis(video_id: UUID) -> dict | None:
    """Load a complete result in the same shape as the upload response."""
    with psycopg.connect(_database_url(), connect_timeout=3, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM videos WHERE id = %s", (video_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            def children(table: str, order_column: str) -> list[dict]:
                # Only fixed, local identifiers are passed to this helper.
                cursor.execute(
                    f"SELECT * FROM {table} WHERE video_id = %s ORDER BY {order_column}",
                    (video_id,),
                )
                return cursor.fetchall()

            segments = children("transcript_segments", "segment_index")
            scenes = children("scenes", "scene_number")
            detections = children("on_screen_text", "detection_index")
            events = children("motion_events", "event_index")
            cursor.execute(
                """SELECT source, view_count, like_count, comment_count, share_count
                FROM video_performance WHERE video_id = %s""",
                (video_id,),
            )
            performance = cursor.fetchone()

    def number(value):
        return float(value) if value is not None else None

    return {
        "video_id": str(row["id"]),
        "metadata": {
            "duration_seconds": number(row["duration_seconds"]),
            "container": row["container"], "file_size_bytes": row["file_size_bytes"],
            "overall_bit_rate": row["overall_bit_rate"],
            "video": {
                "codec": row["video_codec"], "codec_long_name": row["video_codec_long_name"],
                "resolution": {"width": row["width"], "height": row["height"]},
                "fps": number(row["fps"]), "source_fps": number(row["source_fps"]),
                "pixel_format": row["pixel_format"], "bit_rate": row["video_bit_rate"],
                "frame_count": row["frame_count"],
            },
            "audio": {
                "codec": row["audio_codec"], "codec_long_name": row["audio_codec_long_name"],
                "sample_rate": row["audio_sample_rate"], "channels": row["audio_channels"],
                "channel_layout": row["audio_channel_layout"], "bit_rate": row["audio_bit_rate"],
            },
        },
        "audio": {
            "text": row["transcript_text"],
            "segments": [{"start": number(item["start_seconds"]),
                          "end": number(item["end_seconds"]), "text": item["text"]}
                         for item in segments],
        },
        "scenes": [{key: number(value) if key.endswith("seconds") else value
                    for key, value in item.items() if key != "video_id"} for item in scenes],
        "on_screen_text": [{key: number(value) if key == "confidence" or key.endswith("seconds") else value
                            for key, value in item.items() if key not in ("video_id", "detection_index")}
                           for item in detections],
        "motion_events": [{key: number(value) if key == "confidence" or key.endswith("seconds") else value
                           for key, value in item.items() if key not in ("video_id", "event_index")}
                          for item in events],
        **(performance_snapshot(performance["source"], performance) if performance is not None else {}),
    }


class PerformanceSourceConflict(ValueError):
    """The single stored snapshot belongs to a different provider."""


def save_performance(video_id: UUID, performance: dict) -> bool:
    """Attach/refresh one snapshot atomically, preserving other analysis data.

    Return False for an unknown video; never replace another provider's snapshot.
    """
    snapshot = performance_snapshot(performance["performance_source"], performance["performance_metrics"])
    counts = snapshot["performance_metrics"]
    with psycopg.connect(_database_url(), connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            # Serialize metric updates for this UUID, including the first insert.
            cursor.execute("SELECT id FROM videos WHERE id = %s FOR UPDATE", (video_id,))
            if cursor.fetchone() is None:
                return False
            cursor.execute("SELECT source FROM video_performance WHERE video_id = %s", (video_id,))
            existing = cursor.fetchone()
            if existing is not None and existing[0] != snapshot["performance_source"]:
                raise PerformanceSourceConflict("Video already has performance from a different source.")
            cursor.execute(
                """INSERT INTO video_performance
                (video_id, source, view_count, like_count, comment_count, share_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (video_id) DO UPDATE SET
                    view_count = EXCLUDED.view_count,
                    like_count = EXCLUDED.like_count,
                    comment_count = EXCLUDED.comment_count,
                    share_count = EXCLUDED.share_count,
                    fetched_at = now()""",
                (video_id, snapshot["performance_source"], counts["view_count"], counts["like_count"],
                 counts["comment_count"], counts["share_count"]),
            )
    return True
