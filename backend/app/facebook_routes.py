"""Attach Facebook video/Reel metrics to an existing analyzed video."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import facebook, meta
from app.meta_routes import _private
from app.video_repository import PerformanceSourceConflict, get_analysis, save_performance

router = APIRouter(deprecated=True, prefix="/api/meta/facebook")


class FacebookMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: UUID
    page_id: str = Field(pattern=r"^[0-9]{1,30}$")


@router.post("/{media_kind}/{facebook_video_id}/metrics")
def fetch_video_metrics(
    request: Request,
    media_kind: facebook.MediaKind,
    body: FacebookMetricsRequest,
    facebook_video_id: str = Path(pattern=r"^[0-9]{1,30}$"),
):
    session_id = request.cookies.get(meta.SESSION_COOKIE)
    try:
        client = meta.session_client(session_id)
        analysis = get_analysis(body.video_id)
        if analysis is None:
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
        if analysis.get("performance_source") not in (None, "facebook"):
            raise PerformanceSourceConflict("Video already has performance from a different source.")
        performance = facebook.video_performance(client, body.page_id, facebook_video_id, media_kind)
        if not save_performance(body.video_id, performance):
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        meta.remove_session(session_id)
        response = JSONResponse({"detail": "Meta account is not connected. Connect again."}, status_code=401)
        response.delete_cookie(meta.SESSION_COOKIE, path="/api/meta", secure=True, httponly=True, samesite="lax")
    except (facebook.InvalidFacebookVideo, facebook.FacebookMetricsUnavailable) as error:
        response = JSONResponse({"detail": str(error)}, status_code=422)
    except PerformanceSourceConflict:
        response = JSONResponse({"detail": "Video already has performance from a different source."}, status_code=409)
    except meta.MetaPermissionError as error:
        response = JSONResponse({"detail": str(error)}, status_code=403)
    except meta.MetaError:
        response = JSONResponse({"detail": "Facebook metrics request failed."}, status_code=502)
    except (psycopg.Error, ValueError):
        response = JSONResponse({"detail": "Database is unavailable or not configured."}, status_code=503)
    else:
        response = JSONResponse({"video_id": str(body.video_id), **performance})
    return _private(response)
