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
