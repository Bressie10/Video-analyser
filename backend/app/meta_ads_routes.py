"""Attach Meta ad metrics to an existing analyzed video."""

from datetime import date
from uuid import UUID

import psycopg
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, model_validator

from app import meta_ads, meta
from app.meta_routes import _private
from app.video_repository import PerformanceSourceConflict, get_analysis, save_performance

router = APIRouter(deprecated=True, prefix="/api/meta/ads")


class AdMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: UUID
    since: date
    until: date

    @model_validator(mode="after")
    def ordered_range(self):
        if self.since > self.until:
            raise ValueError("since must be on or before until.")
        return self


@router.post("/{ad_id}/metrics")
def fetch_ad_metrics(
    request: Request,
    body: AdMetricsRequest,
    ad_id: str = Path(pattern=r"^[0-9]{1,30}$"),
):
    session_id = request.cookies.get(meta.SESSION_COOKIE)
    try:
        client = meta.session_client(session_id)
        analysis = get_analysis(body.video_id)
        if analysis is None:
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
        if analysis.get("performance_source") not in (None, "meta_ads"):
            raise PerformanceSourceConflict("Video already has performance from a different source.")
        performance = meta_ads.ad_performance(client, ad_id, body.since, body.until)
        if not save_performance(body.video_id, performance):
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        meta.remove_session(session_id)
        response = JSONResponse({"detail": "Meta account is not connected. Connect again."}, status_code=401)
        response.delete_cookie(meta.SESSION_COOKIE, path="/api/meta", secure=True, httponly=True, samesite="lax")
    except meta_ads.AdMetricsUnavailable as error:
        response = JSONResponse({"detail": str(error)}, status_code=422)
    except PerformanceSourceConflict:
        response = JSONResponse({"detail": "Video already has performance from a different source."}, status_code=409)
    except meta.MetaPermissionError as error:
        response = JSONResponse({"detail": str(error)}, status_code=403)
    except meta.MetaError:
        response = JSONResponse({"detail": "Meta Ads metrics request failed."}, status_code=502)
    except (psycopg.Error, ValueError):
        response = JSONResponse({"detail": "Database is unavailable or not configured."}, status_code=503)
    else:
        response = JSONResponse({"video_id": str(body.video_id), **performance})
    return _private(response)
