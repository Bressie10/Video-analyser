import os
import hmac
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import psycopg
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from openai import OpenAIError
from dotenv import load_dotenv

from app.recommendations import MissingAPIKeyError, recommend_videos
from app import tiktok
from app.meta_routes import router as meta_router
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
app.include_router(meta_router)
MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return a minimal liveness response for local development."""
    return {"status": "ok"}


@app.get("/api/tiktok/connect")
def connect_tiktok() -> RedirectResponse:
    """Start web OAuth with a browser-bound anti-forgery state."""
    try:
        config = tiktok.settings()
    except tiktok.TikTokConfigurationError:
        raise HTTPException(status_code=503, detail="TikTok is not configured.") from None
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(tiktok.authorization_url(config, state), status_code=302)
    response.set_cookie(
        tiktok.STATE_COOKIE, state, max_age=tiktok.STATE_MAX_AGE,
        secure=True, httponly=True, samesite="lax", path="/api/tiktok/callback",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiktok/callback")
def tiktok_callback(request: Request) -> JSONResponse:
    """Exchange TikTok's authorization code without exposing tokens."""
    state = request.query_params.get("state")
    stored_state = request.cookies.get(tiktok.STATE_COOKIE)
    if not state or not stored_state or not hmac.compare_digest(state, stored_state):
        response = JSONResponse({"detail": "Invalid TikTok authorization state."}, status_code=400)
    elif request.query_params.get("error") or not request.query_params.get("code"):
        response = JSONResponse({"detail": "TikTok authorization was not completed."}, status_code=400)
    else:
        try:
            tokens = tiktok.exchange_code(tiktok.settings(), request.query_params["code"])
        except tiktok.TikTokError:
            response = JSONResponse({"detail": "TikTok authorization failed."}, status_code=502)
        else:
            session_id = tiktok.create_session(tokens)
            response = JSONResponse({"connected": True})
            response.set_cookie(
                tiktok.SESSION_COOKIE, session_id, max_age=tiktok.SESSION_MAX_AGE,
                secure=True, httponly=True, samesite="lax", path="/api",
            )
    response.delete_cookie(tiktok.STATE_COOKIE, path="/api/tiktok/callback", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/tiktok/videos")
def tiktok_videos(request: Request, response: Response, cursor: int | None = Query(default=None, ge=0)) -> dict:
    """Return one page of the authorized user's public videos and counts."""
    try:
        config = tiktok.settings()
        access_token = tiktok.access_token_for_session(request.cookies.get(tiktok.SESSION_COOKIE), config)
        videos = tiktok.list_videos(access_token, cursor)
    except tiktok.TikTokConfigurationError:
        raise HTTPException(status_code=503, detail="TikTok is not configured.") from None
    except tiktok.TikTokNotConnected:
        raise HTTPException(status_code=401, detail="TikTok account is not connected.") from None
    except tiktok.TikTokError:
        raise HTTPException(status_code=502, detail="TikTok request failed.") from None
    response.headers["Cache-Control"] = "no-store"
    return videos


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
async def upload_video(
    request: Request,
    video: UploadFile = File(...),
    tiktok_url: str | None = Form(default=None),
) -> dict[str, object]:
    """Validate, normalise, and extract PCM WAV audio from a video upload."""
    filename = video.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video format.")

    performance = None
    if tiktok_url and tiktok_url.strip():
        if not os.environ.get("DATABASE_URL"):
            raise HTTPException(status_code=503, detail="Database is not configured.")
        try:
            tiktok_video_id = tiktok.video_id_from_url(tiktok_url)
        except tiktok.TikTokError:
            raise HTTPException(status_code=422, detail="Enter a full TikTok video URL.") from None
        try:
            config = tiktok.settings()
            access_token = tiktok.access_token_for_session(request.cookies.get(tiktok.SESSION_COOKIE), config)
            performance = tiktok.video_performance(access_token, tiktok_video_id)
        except tiktok.TikTokConfigurationError:
            raise HTTPException(status_code=503, detail="TikTok is not configured.") from None
        except tiktok.TikTokNotConnected:
            raise HTTPException(status_code=401, detail="TikTok account is not connected.") from None
        except tiktok.TikTokVideoNotFound:
            raise HTTPException(status_code=404, detail="TikTok video was not found for this account.") from None
        except tiktok.TikTokError:
            raise HTTPException(status_code=502, detail="TikTok performance request failed.") from None

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
    if performance is not None:
        analysis.update(performance)
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
