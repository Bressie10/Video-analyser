"""Attach Meta ad metrics to an existing analyzed video."""

from datetime import date
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, model_validator

from app.auth import AuthenticatedUser, require_authenticated_user
from app import meta_ads, meta, meta_library_repository as library
from app import performance_observation_repository as observations
from app.meta_auth_dependencies import require_meta_session
from app.meta_routes import _private
from app.video_repository import PerformanceSourceConflict, get_analysis, save_performance

router = APIRouter(dependencies=[Depends(require_meta_session)], deprecated=True, prefix="/api/meta/ads")


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
    *,
    user: AuthenticatedUser = Depends(require_authenticated_user),
    body: AdMetricsRequest,
    ad_id: str = Path(pattern=r"^[0-9]{1,30}$"),
):
    session_id = request.cookies.get(meta.SESSION_COOKIE)
    try:
        client = meta.session_client(session_id)
        analysis = get_analysis(body.video_id, owner_user_id=user.user_id)
        if analysis is None:
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
        if analysis.get("performance_source") not in (None, "meta_ads"):
            raise PerformanceSourceConflict("Video already has performance from a different source.")
        performance = meta_ads.ad_performance(client, ad_id, body.since, body.until)
        if not save_performance(body.video_id, performance, owner_user_id=user.user_id):
            return _private(JSONResponse({"detail": "Video analysis not found."}, status_code=404))
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        meta.remove_session(session_id)
        response = JSONResponse({"detail": "Meta account is not connected. Connect again."}, status_code=401, headers={"X-ContentMetric-Auth": "provider"})
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


class CompanyAdMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    since: date
    until: date

    @model_validator(mode="after")
    def ordered_range(self):
        if self.since > self.until:
            raise ValueError("since must be on or before until.")
        return self


@router.post("/companies/{company_id}/items/{ad_item_id}/metrics")
def fetch_company_ad_metrics(
    request: Request, company_id: UUID, ad_item_id: UUID,
    body: CompanyAdMetricsRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
):
    """Fetch one assigned ad and append an immutable company observation."""
    session_id = request.cookies.get(meta.SESSION_COOKIE)
    try:
        connection = library.session_connection(session_id)
        assigned = observations.authorized_ad(user, company_id, connection["id"], ad_item_id)
        client = library.connection_client(connection)
        performance, identity = meta_ads.ad_performance_with_identity(
            client, assigned["ad_id"], body.since, body.until)
        stored = observations.save_meta_ad_observation(
            user, company_id, connection["id"], ad_item_id, identity, performance)
    except HTTPException as error:
        response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
    except observations.ObservationOwnershipError:
        response = JSONResponse({"detail": "Company ad was not found."}, status_code=404)
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        response = JSONResponse({"detail": "Meta account is not connected. Connect again."}, status_code=401)
    except meta_ads.AdMetricsUnavailable as error:
        response = JSONResponse({"detail": str(error)}, status_code=422)
    except PerformanceSourceConflict:
        response = JSONResponse({"detail": "Video already has performance from a different source."}, status_code=409)
    except meta.MetaPermissionError:
        response = JSONResponse({"detail": "Meta permission is required."}, status_code=403)
    except meta.MetaError:
        response = JSONResponse({"detail": "Meta Ads metrics request failed."}, status_code=502)
    except (psycopg.Error, ValueError, KeyError):
        response = JSONResponse({"detail": "Performance history is unavailable."}, status_code=503)
    else:
        response = JSONResponse({"observation_id": str(stored["id"]),
                                 "fetched_at": stored["fetched_at"].isoformat(),
                                 **performance})
    return _private(response)
