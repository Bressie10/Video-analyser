"""Local validation and normalisation helpers for uploaded videos."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_DURATION_SECONDS = 10 * 60
MAX_PROCESSING_DIMENSION = 1920
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
SUPPORTED_CONTAINERS = {
    ".mp4": {"mov", "mp4"},
    ".mov": {"mov", "mp4"},
    ".mkv": {"matroska"},
    ".webm": {"webm", "matroska"},
}


class VideoProcessingError(ValueError):
    """Raised when an upload cannot be safely processed as a video."""


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    has_audio: bool


def inspect_video(video_path: Path) -> VideoMetadata:
    """Confirm a file is readable and contains a supported video stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_type",
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

    stream_types = {stream.get("codec_type") for stream in probe.get("streams", [])}
    format_names = set(probe["format"].get("format_name", "").split(","))
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

    return VideoMetadata(duration_seconds=duration, has_audio=True)


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
