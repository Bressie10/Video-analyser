import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import psycopg
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from openai import OpenAIError
from dotenv import load_dotenv

from app.recommendations import MissingAPIKeyError, recommend_videos
from app.video_repository import get_analysis, save_analysis

from app.video_processing import (
    SUPPORTED_EXTENSIONS,
    VideoProcessingError,
    detect_motion_events,
    detect_on_screen_text,
    detect_scenes,
    extract_wav_audio,
    inspect_video,
    normalise_video,
    transcribe_audio,
)

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

app = FastAPI(title="Video Analyzer API")
MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return a minimal liveness response for local development."""
    return {"status": "ok"}


@app.get("/health/db")
def database_health_check() -> dict[str, str]:
    """Check that the configured PostgreSQL database answers a simple query."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Database is not configured.")

    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="Database is unavailable.") from error

    return {"status": "ok"}


@app.post("/api/photos")
async def upload_photo(photo: UploadFile = File(...)) -> dict[str, str]:
    """Accept an image upload for later analysis without persisting it."""
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are supported.")

    return {
        "filename": photo.filename or "unnamed image",
        "content_type": photo.content_type,
        "status": "received",
    }


@app.post("/api/videos")
async def upload_video(video: UploadFile = File(...)) -> dict[str, object]:
    """Validate, normalise, and extract PCM WAV audio from a video upload."""
    filename = video.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video format.")

    with TemporaryDirectory(prefix="video-analyzer-") as directory:
        source_path = Path(directory, f"source{suffix}")
        size = 0
        with source_path.open("wb") as source_file:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds the 500 MiB limit.")
                source_file.write(chunk)

        try:
            metadata = inspect_video(source_path)
            normalised_path = Path(directory, "normalised.mp4")
            normalise_video(source_path, normalised_path)
            scenes = detect_scenes(normalised_path)
            on_screen_text = detect_on_screen_text(normalised_path)
            motion_events = detect_motion_events(normalised_path)
            audio_path = Path(directory, "audio.wav")
            extract_wav_audio(normalised_path, audio_path)
            transcription = transcribe_audio(audio_path)
        except VideoProcessingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    analysis = {
        "metadata": metadata.as_dict(),
        "audio": transcription,
        "scenes": scenes,
        "on_screen_text": on_screen_text,
        "motion_events": motion_events,
    }
    if os.environ.get("DATABASE_URL"):
        try:
            video_id = save_analysis(analysis)
        except psycopg.Error as error:
            raise HTTPException(status_code=503, detail="Database is unavailable.") from error
        return {"video_id": video_id, **analysis}
    return analysis


def _stored_analysis(video_id: UUID) -> dict:
    try:
        analysis = get_analysis(video_id)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="Database is unavailable.") from error
    if analysis is None:
        raise HTTPException(status_code=404, detail="Video analysis not found.")
    return analysis


@app.get("/api/videos/{video_id}/analysis")
def read_video_analysis(video_id: UUID) -> dict:
    """Expose stored metadata and analysis to API clients."""
    return _stored_analysis(video_id)


@app.post("/api/videos/{video_id}/recommendations")
def create_video_recommendations(
    video_id: UUID,
    runtime_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
) -> dict[str, str]:
    """Ask GPT-6 Sol to recommend future videos from stored analysis."""
    analysis = _stored_analysis(video_id)
    try:
        return recommend_videos(analysis, api_key=runtime_api_key)
    except MissingAPIKeyError as error:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured.") from error
    except OpenAIError:
        raise HTTPException(status_code=502, detail="OpenAI request failed.") from None
