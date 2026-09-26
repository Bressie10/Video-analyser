"""Backend-only Meta authorization and connection check routes."""

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import meta

router = APIRouter(prefix="/api/meta")


def _private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/connect")
def connect():
    try:
        state, url = meta.begin_login(meta.settings())
    except meta.MetaConfigurationError:
        return _private(JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503))
    except meta.MetaError:
        return _private(JSONResponse({"detail": "Meta login is unavailable. Try again later."}, status_code=503))
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        meta.STATE_COOKIE, state, max_age=meta.STATE_MAX_AGE,
        secure=True, httponly=True, samesite="lax", path="/api/meta/callback",
    )
    return _private(response)


@router.get("/callback")
def callback(request: Request):
    try:
        config = meta.consume_state(request.query_params.get("state"), request.cookies.get(meta.STATE_COOKIE))
    except meta.MetaError:
        response = JSONResponse({"detail": "Invalid Meta authorization state."}, status_code=400)
    else:
        code = request.query_params.get("code")
        if request.query_params.get("error") or not code:
            response = JSONResponse({"detail": "Meta authorization was not completed."}, status_code=400)
        else:
            try:
                token = meta.exchange_code(config, code)
                client = meta.MetaClient(config, token)
                client.verify_permissions()
                result = client.test_connection()
            except meta.MetaPermissionError as error:
                response = JSONResponse({"detail": str(error)}, status_code=403)
            except meta.MetaError:
                response = JSONResponse({"detail": "Meta authorization failed. Connect again."}, status_code=502)
            else:
                session_id = meta.create_session(token, request.cookies.get(meta.SESSION_COOKIE))
                response = JSONResponse(result)
                response.set_cookie(
                    meta.SESSION_COOKIE, session_id, max_age=max(1, int(token.expires_at - time.time())),
                    secure=True, httponly=True, samesite="lax", path="/api/meta",
                )
    response.delete_cookie(meta.STATE_COOKIE, path="/api/meta/callback", secure=True, httponly=True, samesite="lax")
    return _private(response)


@router.get("/test")
def test_connection(request: Request):
    """Report connection status; absence is normal, provider failures are errors."""
    session_id = request.cookies.get(meta.SESSION_COOKIE)
    try:
        result = meta.session_client(session_id).test_connection()
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        meta.remove_session(session_id)
        response = JSONResponse({"connected": False})
        response.delete_cookie(meta.SESSION_COOKIE, path="/api/meta", secure=True, httponly=True, samesite="lax")
    except meta.MetaPermissionError:
        response = JSONResponse({"detail": "Meta permission is required. Reconnect and grant access."}, status_code=403)
    except meta.MetaError:
        response = JSONResponse({"detail": "Meta API request failed."}, status_code=502)
    else:
        response = JSONResponse(result)
    return _private(response)
