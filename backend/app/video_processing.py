"""Local validation and normalisation helpers for uploaded videos."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MAX_DURATION_SECONDS = 10 * 60
MAX_PROCESSING_DIMENSION = 1920
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
SCENE_DETECTION_THRESHOLD = 27.0
TEXT_SAMPLE_RATE_FPS = 2.0
MIN_TEXT_CONFIDENCE = 0.6
TEXT_BOX_MATCH_IOU = 0.5
MOTION_SAMPLE_RATE_FPS = 8.0
MOTION_MAGNITUDE_THRESHOLD = 0.75
GLOBAL_MOTION_COVERAGE = 0.55
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
SUPPORTED_CONTAINERS = {
    ".mp4": {"mov", "mp4"},
    ".mov": {"mov", "mp4"},
    ".mkv": {"matroska"},
    ".webm": {"webm", "matroska"},
}


class VideoProcessingError(ValueError):
    """Raised when an upload cannot be safely processed as a video."""


class AudioTranscriptionError(VideoProcessingError):
    """Raised when extracted audio cannot be transcribed."""


class SceneDetectionError(VideoProcessingError):
    """Raised when scene-change detection cannot complete."""


class TextDetectionError(VideoProcessingError):
    """Raised when on-screen text detection cannot complete."""


class MotionDetectionError(VideoProcessingError):
    """Raised when optical-flow motion detection cannot complete."""


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    container: str
    file_size_bytes: int
    overall_bit_rate: int | None
    video: dict[str, Any]
    audio: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-compatible video metadata for the API response."""
        return {
            "duration_seconds": round(self.duration_seconds, 3),
            "container": self.container,
            "file_size_bytes": self.file_size_bytes,
            "overall_bit_rate": self.overall_bit_rate,
            "video": self.video,
            "audio": self.audio,
        }


def _integer(value: str | None) -> int | None:
    """Convert optional ffprobe numeric values without exposing sentinel values."""
    if not value or value == "N/A":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _frame_rate(value: str | None) -> float | None:
    """Convert ffprobe's fractional frame-rate field to frames per second."""
    if not value or value == "N/A":
        return None
    try:
        numerator, denominator = (int(part) for part in value.split("/", maxsplit=1))
        if denominator == 0:
            return None
        return round(numerator / denominator, 3)
    except (TypeError, ValueError):
        return None


def inspect_video(video_path: Path) -> VideoMetadata:
    """Confirm a file is readable and contains a supported video stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,format_name,size,bit_rate:"
                    "stream=index,codec_type,codec_name,codec_long_name,width,height,"
                    "avg_frame_rate,r_frame_rate,pix_fmt,bit_rate,nb_frames,"
                    "sample_rate,channels,channel_layout"
                ),
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        raise VideoProcessingError("The video is corrupted or unreadable.") from error

    streams = probe.get("streams", [])
    stream_types = {stream.get("codec_type") for stream in streams}
    format_data = probe["format"]
    format_names = set(format_data.get("format_name", "").split(","))
    if not format_names.intersection(SUPPORTED_CONTAINERS[video_path.suffix.lower()]):
        raise VideoProcessingError("The uploaded file is not a supported video container.")
    if "video" not in stream_types:
        raise VideoProcessingError("The uploaded file does not contain a video stream.")
    if "audio" not in stream_types:
        raise VideoProcessingError("The uploaded video must contain an audio stream.")
    if duration <= 0 or duration > MAX_DURATION_SECONDS:
        raise VideoProcessingError(
            f"Video duration must be between 1 second and {MAX_DURATION_SECONDS} seconds.",
        )

    video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio_stream = next(stream for stream in streams if stream.get("codec_type") == "audio")

    return VideoMetadata(
        duration_seconds=duration,
        container=format_data["format_name"],
        file_size_bytes=_integer(format_data.get("size")) or video_path.stat().st_size,
        overall_bit_rate=_integer(format_data.get("bit_rate")),
        video={
            "codec": video_stream.get("codec_name"),
            "codec_long_name": video_stream.get("codec_long_name"),
            "resolution": {
                "width": _integer(video_stream.get("width")),
                "height": _integer(video_stream.get("height")),
            },
            "fps": _frame_rate(video_stream.get("avg_frame_rate")),
            "source_fps": _frame_rate(video_stream.get("r_frame_rate")),
            "pixel_format": video_stream.get("pix_fmt"),
            "bit_rate": _integer(video_stream.get("bit_rate")),
            "frame_count": _integer(video_stream.get("nb_frames")),
        },
        audio={
            "codec": audio_stream.get("codec_name"),
            "codec_long_name": audio_stream.get("codec_long_name"),
            "sample_rate": _integer(audio_stream.get("sample_rate")),
            "channels": _integer(audio_stream.get("channels")),
            "channel_layout": audio_stream.get("channel_layout"),
            "bit_rate": _integer(audio_stream.get("bit_rate")),
        },
    )


def normalise_video(source_path: Path, output_path: Path) -> None:
    """Create an MP4 with H.264 video, AAC audio, and capped dimensions."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source_path),
                "-vf",
                (
                    f"scale=w='min({MAX_PROCESSING_DIMENSION},iw)':"
                    f"h='min({MAX_PROCESSING_DIMENSION},ih)':"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2"
                ),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise VideoProcessingError("The video could not be normalised.") from error


def extract_wav_audio(source_path: Path, output_path: Path) -> None:
    """Extract mono 16 kHz PCM WAV audio for future transcription work."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise VideoProcessingError("Audio could not be extracted from the video.") from error


@lru_cache(maxsize=1)
def _whisper_model() -> Any:
    """Load the local transcription model once, on the first audio request."""
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
    except Exception as error:
        raise AudioTranscriptionError("The transcription model could not be loaded.") from error


def transcribe_audio(audio_path: Path) -> dict[str, Any]:
    """Return the complete transcript and timestamped faster-whisper segments."""
    try:
        segments, _ = _whisper_model().transcribe(str(audio_path), beam_size=5, vad_filter=True)
        timestamped_segments = [
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
            }
            for segment in segments
            if segment.text.strip()
        ]
    except AudioTranscriptionError:
        raise
    except Exception as error:
        raise AudioTranscriptionError("Audio transcription failed.") from error

    return {
        "text": " ".join(segment["text"] for segment in timestamped_segments),
        "segments": timestamped_segments,
    }


def detect_scenes(video_path: Path) -> list[dict[str, float | int | None]]:
    """Return content-based scene boundaries from a normalised video."""
    try:
        from scenedetect import ContentDetector, detect

        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=SCENE_DETECTION_THRESHOLD),
            show_progress=False,
        )
    except Exception as error:
        raise SceneDetectionError("Scene changes could not be detected.") from error

    return [
        {
            "scene_number": index,
            "start_seconds": round(start.get_seconds(), 3),
            "end_seconds": round(end.get_seconds(), 3),
            "duration_seconds": round(end.get_seconds() - start.get_seconds(), 3),
            "cut_timestamp_seconds": None if index == 1 else round(start.get_seconds(), 3),
        }
        for index, (start, end) in enumerate(scene_list, start=1)
    ]


@lru_cache(maxsize=1)
def _ocr_model() -> Any:
    """Load the ONNX OCR pipeline once, only when a video needs text analysis."""
    try:
        from rapidocr import RapidOCR

        return RapidOCR()
    except Exception as error:
        raise TextDetectionError("The on-screen text detector could not be loaded.") from error


def _normalise_detected_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _box_iou(first_box: list[list[int]], second_box: list[list[int]]) -> float:
    """Compare quadrilateral OCR boxes by their enclosing axis-aligned rectangles."""
    first_x = [point[0] for point in first_box]
    first_y = [point[1] for point in first_box]
    second_x = [point[0] for point in second_box]
    second_y = [point[1] for point in second_box]
    first_left, first_top, first_right, first_bottom = min(first_x), min(first_y), max(first_x), max(first_y)
    second_left, second_top, second_right, second_bottom = (
        min(second_x),
        min(second_y),
        max(second_x),
        max(second_y),
    )
    intersection_width = max(0, min(first_right, second_right) - max(first_left, second_left))
    intersection_height = max(0, min(first_bottom, second_bottom) - max(first_top, second_top))
    intersection = intersection_width * intersection_height
    union = (
        (first_right - first_left) * (first_bottom - first_top)
        + (second_right - second_left) * (second_bottom - second_top)
        - intersection
    )
    return intersection / union if union else 0.0


def detect_on_screen_text(video_path: Path) -> list[dict[str, Any]]:
    """Sample frames and group recurring OCR detections into visible text intervals."""
    try:
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise TextDetectionError("The normalised video could not be read for text detection.")

        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise TextDetectionError("The normalised video has no readable frames.")
        sample_interval_frames = max(1, round(fps / TEXT_SAMPLE_RATE_FPS))
        sample_interval_seconds = sample_interval_frames / fps
        video_duration = frame_count / fps
        tracks: list[dict[str, Any]] = []
        completed_tracks: list[dict[str, Any]] = []
        frame_number = 0

        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number % sample_interval_frames:
                frame_number += 1
                continue

            timestamp = frame_number / fps
            result = _ocr_model()(frame)
            boxes = result.boxes if result.boxes is not None else ()
            texts = result.txts if result.txts is not None else ()
            scores = result.scores if result.scores is not None else ()
            detections = [
                {
                    "text": text.strip(),
                    "normalised_text": _normalise_detected_text(text),
                    "bounding_box": [[int(round(value)) for value in point] for point in box],
                    "confidence": round(float(score), 3),
                }
                for box, text, score in zip(boxes, texts, scores)
                if text.strip() and float(score) >= MIN_TEXT_CONFIDENCE
            ]
            matched_track_ids: set[int] = set()

            for detection in detections:
                matching_track = next(
                    (
                        track
                        for track in tracks
                        if track["id"] not in matched_track_ids
                        and track["normalised_text"] == detection["normalised_text"]
                        and _box_iou(track["bounding_box"], detection["bounding_box"])
                        >= TEXT_BOX_MATCH_IOU
                    ),
                    None,
                )
                if matching_track is None:
                    matching_track = {
                        "id": len(tracks) + len(completed_tracks),
                        "text": detection["text"],
                        "normalised_text": detection["normalised_text"],
                        "bounding_box": detection["bounding_box"],
                        "confidence": detection["confidence"],
                        "start_seconds": timestamp,
                        "last_seen_seconds": timestamp,
                    }
                    tracks.append(matching_track)
                else:
                    matching_track["last_seen_seconds"] = timestamp
                    if detection["confidence"] > matching_track["confidence"]:
                        matching_track["confidence"] = detection["confidence"]
                        matching_track["bounding_box"] = detection["bounding_box"]
                matched_track_ids.add(matching_track["id"])

            still_visible: list[dict[str, Any]] = []
            for track in tracks:
                if track["id"] in matched_track_ids:
                    still_visible.append(track)
                    continue
                track["disappearance_timestamp_seconds"] = round(timestamp, 3)
                completed_tracks.append(track)
            tracks = still_visible
            frame_number += 1

        for track in tracks:
            track["disappearance_timestamp_seconds"] = round(video_duration, 3)
            completed_tracks.append(track)
    except TextDetectionError:
        raise
    except Exception as error:
        raise TextDetectionError("On-screen text detection failed.") from error
    finally:
        if "capture" in locals():
            capture.release()

    return [
        {
            "text": track["text"],
            "bounding_box": track["bounding_box"],
            "confidence": track["confidence"],
            "appearance_timestamp_seconds": round(track["start_seconds"], 3),
            "disappearance_timestamp_seconds": track["disappearance_timestamp_seconds"],
        }
        for track in completed_tracks
    ]


def _motion_strength(magnitude: float) -> float:
    """Map sampled-frame displacement to a bounded confidence contribution."""
    return min(1.0, magnitude / 4.0)


def _classify_optical_flow(
    flow: Any,
    direction_history: list[Any],
) -> tuple[str | None, float, Any | None]:
    """Classify a dense flow field from measured coverage and vector patterns."""
    import numpy as np

    magnitudes = np.linalg.norm(flow, axis=2)
    active = magnitudes >= MOTION_MAGNITUDE_THRESHOLD
    active_coverage = float(np.mean(active))
    if active_coverage < 0.01:
        return None, 0.0, None

    active_vectors = flow[active]
    active_magnitudes = magnitudes[active]
    median_vector = np.median(active_vectors, axis=0)
    median_magnitude = float(np.linalg.norm(median_vector))
    mean_magnitude = float(np.mean(active_magnitudes))
    coherence = min(1.0, median_magnitude / max(mean_magnitude, 1e-6))

    height, width = magnitudes.shape
    y_coordinates, x_coordinates = np.indices((height, width), dtype=np.float32)
    radial = np.stack((x_coordinates - width / 2, y_coordinates - height / 2), axis=2)
    radial_norm = np.linalg.norm(radial, axis=2)
    radial[radial_norm > 0] /= radial_norm[radial_norm > 0, None]
    radial_component = np.sum(flow[active] * radial[active], axis=1)
    radial_alignment = abs(float(np.mean(radial_component))) / max(mean_magnitude, 1e-6)

    direction = median_vector / median_magnitude if median_magnitude else None
    if active_coverage >= GLOBAL_MOTION_COVERAGE and direction is not None:
        direction_history.append(direction)
        del direction_history[:-4]
    direction_stability = 1.0
    if len(direction_history) >= 3:
        direction_stability = float(np.linalg.norm(np.mean(direction_history, axis=0)))

    strength = _motion_strength(mean_magnitude)
    if active_coverage >= GLOBAL_MOTION_COVERAGE:
        if len(direction_history) >= 3 and direction_stability < 0.4 and coherence >= 0.45:
            confidence = 0.35 * active_coverage + 0.35 * coherence + 0.3 * (1 - direction_stability)
            return "camera_shake", round(min(1.0, confidence), 3), direction
        if radial_alignment >= 0.6:
            confidence = 0.35 * active_coverage + 0.45 * radial_alignment + 0.2 * strength
            return "camera_zoom", round(min(1.0, confidence), 3), direction
        if coherence >= 0.7:
            confidence = 0.4 * active_coverage + 0.4 * coherence + 0.2 * strength
            return "camera_pan", round(min(1.0, confidence), 3), direction
        if active_coverage >= 0.8:
            confidence = 0.4 * active_coverage + 0.3 * strength + 0.3 * (1 - coherence)
            return "general_motion", round(min(1.0, confidence), 3), direction
        return "unknown", round(0.25 + 0.35 * active_coverage, 3), direction

    if active_coverage <= 0.4:
        confidence = 0.45 * (1 - active_coverage) + 0.3 * strength + 0.25 * (1 - coherence)
        return "local_motion", round(min(1.0, confidence), 3), direction

    confidence = 0.4 * active_coverage + 0.3 * strength + 0.3 * (1 - coherence)
    return "general_motion", round(min(1.0, confidence), 3), direction


def detect_motion_events(video_path: Path) -> list[dict[str, Any]]:
    """Use dense optical flow to identify and timestamp measurable motion patterns."""
    try:
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise MotionDetectionError("The normalised video could not be read for motion detection.")
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise MotionDetectionError("The normalised video has no readable frames.")

        sample_interval_frames = max(1, round(fps / MOTION_SAMPLE_RATE_FPS))
        video_duration = frame_count / fps
        previous_gray = None
        direction_history: list[Any] = []
        active_event: dict[str, Any] | None = None
        motion_events: list[dict[str, Any]] = []
        frame_number = 0

        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number % sample_interval_frames:
                frame_number += 1
                continue

            timestamp = frame_number / fps
            scale = min(1.0, 480 / frame.shape[1])
            resized = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            current_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            if previous_gray is None:
                previous_gray = current_gray
                frame_number += 1
                continue

            flow = cv2.calcOpticalFlowFarneback(
                previous_gray,
                current_gray,
                None,
                0.5,
                3,
                15,
                3,
                5,
                1.2,
                0,
            )
            motion_type, confidence, _ = _classify_optical_flow(flow, direction_history)
            if motion_type is None:
                if active_event is not None:
                    active_event["end"] = round(timestamp, 3)
                    active_event["confidence"] = round(
                        active_event["confidence_total"] / active_event["samples"],
                        3,
                    )
                    del active_event["confidence_total"], active_event["samples"]
                    motion_events.append(active_event)
                    active_event = None
            elif active_event is not None and active_event["type"] == motion_type:
                active_event["end"] = round(timestamp, 3)
                active_event["confidence_total"] += confidence
                active_event["samples"] += 1
            else:
                if active_event is not None:
                    active_event["end"] = round(timestamp, 3)
                    active_event["confidence"] = round(
                        active_event["confidence_total"] / active_event["samples"],
                        3,
                    )
                    del active_event["confidence_total"], active_event["samples"]
                    motion_events.append(active_event)
                active_event = {
                    "start": round(timestamp - sample_interval_frames / fps, 3),
                    "end": round(timestamp, 3),
                    "type": motion_type,
                    "confidence_total": confidence,
                    "samples": 1,
                }

            previous_gray = current_gray
            frame_number += 1

        if active_event is not None:
            active_event["end"] = round(video_duration, 3)
            active_event["confidence"] = round(
                active_event["confidence_total"] / active_event["samples"],
                3,
            )
            del active_event["confidence_total"], active_event["samples"]
            motion_events.append(active_event)
    except MotionDetectionError:
        raise
    except Exception as error:
        raise MotionDetectionError("Optical-flow motion detection failed.") from error
    finally:
        if "capture" in locals():
            capture.release()

    return motion_events
