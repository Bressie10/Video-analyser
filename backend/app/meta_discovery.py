"""Small, read-only selection lists using the existing Meta session client."""

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from app import meta
from app.meta_routes import _private

router = APIRouter(prefix="/api/meta/discovery")
Identifier = Annotated[str, Path(pattern=r"^[0-9]{1,30}$")]
AdAccount = Annotated[str, Path(pattern=r"^act_[0-9]{1,30}$")]
Cursor = Annotated[str | None, Query(max_length=2048)]


def preview(value):
    try:
        if isinstance(value, str):
            parsed = urlsplit(value)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                return value
    except ValueError:
        pass
    return None


def item(row, kind, fallback):
    identifier = row.get("id")
    if not isinstance(identifier, str) or not re.fullmatch(r"(?:act_)?[0-9]{1,30}", identifier):
        raise meta.MetaError("Invalid discovery item.")
    label = next((row[key].strip() for key in ("name", "title", "caption", "description", "username")
                  if isinstance(row.get(key), str) and row[key].strip()), fallback)
    creative = row.get("creative") or {}
    created = row.get("timestamp") or row.get("created_time")
    status = row.get("effective_status")
    if not isinstance(kind, str):
        raise meta.MetaError("Invalid content type.")
    return {"id": identifier, "name": label[:200], "type": kind,
            "created_at": created if isinstance(created, str) else None,
            "status": status if isinstance(status, str) else None,
            "thumbnail": preview(row.get("thumbnail_url") or row.get("picture")
                                 or (creative.get("thumbnail_url") if isinstance(creative, dict) else None))}


def listing(client, path, fields, after, convert):
    params = {"fields": fields, "limit": 25}
    if after:
        params["after"] = after
    payload = client.get(path, params)
    rows = payload.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise meta.MetaError("Invalid discovery list.")
    paging = payload.get("paging", {})
    if not isinstance(paging, dict):
        raise meta.MetaError("Invalid pagination.")
    cursor = None
    if paging.get("next"):
        cursors = paging.get("cursors", {})
        cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor == after:
            raise meta.MetaError("Invalid pagination.")
    return {"items": [convert(row) for row in rows], "next_cursor": cursor}


def respond(request, operation):
    session = request.cookies.get(meta.SESSION_COOKIE)
    try:
        response = JSONResponse(operation(meta.session_client(session)))
    except meta.MetaConfigurationError:
        response = JSONResponse({"detail": "Meta is not configured correctly."}, status_code=503)
    except meta.MetaNotConnected:
        meta.remove_session(session)
        response = JSONResponse({"detail": "Meta is disconnected. Connect Meta again to browse your content."}, status_code=401)
        response.delete_cookie(meta.SESSION_COOKIE, path="/api/meta", secure=True, httponly=True, samesite="lax")
    except meta.MetaPermissionError:
        response = JSONResponse({"detail": "Meta has not granted access to this content. Reconnect Meta and allow access to the selected Page or account."}, status_code=403)
    except meta.MetaError:
        response = JSONResponse({"detail": "Could not load Meta content. Please try again."}, status_code=502)
    return _private(response)


@router.get("/pages")
def pages(request: Request, after: Cursor = None):
    return respond(request, lambda client: listing(client, "me/accounts", "id,name", after,
                   lambda row: item(row, "page", "Facebook Page")))


def instagram_account(client, page_id):
    page = client.for_page(page_id)
    payload = page.get(page_id, {"fields": "instagram_business_account{id,name,username}"})
    account = payload.get("instagram_business_account")
    if account is not None and not isinstance(account, dict):
        raise meta.MetaError("Invalid Instagram account.")
    return account


@router.get("/pages/{page_id}/instagram-accounts")
def instagram_accounts(request: Request, page_id: Identifier):
    def discover(client):
        account = instagram_account(client, page_id)
        return {"items": [item(account, "instagram", "Instagram account")] if account else [], "next_cursor": None}
    return respond(request, discover)


@router.get("/pages/{page_id}/facebook/{kind}")
def facebook_content(request: Request, page_id: Identifier, kind: Literal["videos", "reels"], after: Cursor = None):
    return respond(request, lambda client: listing(client.for_page(page_id),
                   f"{page_id}/{'video_reels' if kind == 'reels' else 'videos'}",
                   "id,title,description,picture,created_time", after,
                   lambda row: item(row, kind, "Facebook Reel" if kind == "reels" else "Facebook video")))


@router.get("/pages/{page_id}/instagram/{account_id}/media")
def instagram_media(request: Request, page_id: Identifier, account_id: Identifier, after: Cursor = None):
    def discover(client):
        account = instagram_account(client, page_id)
        if not account or account.get("id") != account_id:
            raise meta.MetaPermissionError("Instagram account is not connected to this Page.")
        def convert(row):
            result = item(row, row.get("media_product_type") or row.get("media_type") or "Post", "Instagram post")
            result["selectable"] = row.get("media_product_type") == "REELS" and row.get("media_type") == "VIDEO"
            return result
        return listing(client, f"{account_id}/media", "id,caption,media_type,media_product_type,thumbnail_url,timestamp", after, convert)
    return respond(request, discover)


@router.get("/ad-accounts")
def ad_accounts(request: Request, after: Cursor = None):
    return respond(request, lambda client: listing(client, "me/adaccounts", "id,name", after,
                   lambda row: item(row, "ad_account", "Advertising account")))


@router.get("/ad-accounts/{account_id}/ads")
def ads(request: Request, account_id: AdAccount, after: Cursor = None):
    return respond(request, lambda client: listing(client, f"{account_id}/ads",
                   "id,name,effective_status,created_time,creative{thumbnail_url}", after,
                   lambda row: item(row, "Ad", "Untitled ad")))
