"""Provider cookies select connections; verified app users authorize them."""
import psycopg
from fastapi import Depends, HTTPException, Request
from app import meta, meta_library_repository as repo
from app.auth import AuthenticatedUser, require_authenticated_user


def owned_session_connection(request: Request, user: AuthenticatedUser):
    try:
        connection = repo.session_connection(request.cookies.get(meta.SESSION_COOKIE))
    except (psycopg.Error, ValueError):
        raise HTTPException(503, 'Meta storage is unavailable.', headers={'Cache-Control': 'no-store'}) from None
    if connection.get('owner_user_id') != user.user_id:
        raise HTTPException(403, 'Meta connection access denied.', headers={'Cache-Control': 'no-store'})
    return connection


def require_meta_session(request: Request,
                         user: AuthenticatedUser = Depends(require_authenticated_user)):
    try:
        request.state.meta_connection = owned_session_connection(request, user)
    except meta.MetaNotConnected:
        raise HTTPException(401, 'Reconnect Meta to continue.', headers={'Cache-Control': 'no-store', 'X-ContentMetric-Auth': 'provider'}) from None
