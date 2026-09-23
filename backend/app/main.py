from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, File, HTTPException, UploadFile

from app.video_processing import (
    SUPPORTED_EXTENSIONS,
    VideoProcessingError,
    extract_wav_audio,
    inspect_video,
    normalise_video,
)

app = FastAPI(title="Video Analyzer API")
MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return a minimal liveness response for local development."""
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
async def upload_video(video: UploadFile = File(...)) -> dict[str, str | float]:
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
            extract_wav_audio(normalised_path, Path(directory, "audio.wav"))
        except VideoProcessingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return {
        "filename": filename,
        "duration_seconds": round(metadata.duration_seconds, 2),
        "normalised_container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
        "extracted_audio": "wav (PCM s16le, mono, 16 kHz)",
        "status": "processed",
    }
