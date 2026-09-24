import os
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg
from fastapi import FastAPI, File, HTTPException, UploadFile

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

    return {
        "metadata": metadata.as_dict(),
        "audio": transcription,
        "scenes": scenes,
        "on_screen_text": on_screen_text,
        "motion_events": motion_events,
    }
