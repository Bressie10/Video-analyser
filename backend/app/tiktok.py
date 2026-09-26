"""Minimal server-side TikTok OAuth and public-video access."""

import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx

from app.performance import VideoPerformance, performance_snapshot

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"
SCOPE = "video.list"
VIDEO_FIELDS = (
    "id", "create_time", "title", "video_description", "duration",
    "view_count", "like_count", "comment_count", "share_count",
)
PERFORMANCE_FIELDS = ("view_count", "like_count", "comment_count", "share_count")
STATE_COOKIE = "tiktok_oauth_state"
SESSION_COOKIE = "tiktok_session"
STATE_MAX_AGE = 600
SESSION_MAX_AGE = 30 * 24 * 60 * 60


class TikTokError(Exception):
    """A safe, client-facing TikTok integration error."""


class TikTokConfigurationError(TikTokError):
    """Required server-side TikTok settings are missing or invalid."""


class TikTokNotConnected(TikTokError):
    """The browser has no usable TikTok authorization."""


class TikTokVideoNotFound(TikTokError):
    """The authorized user does not have the requested public video."""


@dataclass(frozen=True)
class TikTokSettings:
    client_key: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class UserTokens:
    access_token: str
    refresh_token: str | None
    expires_at: float
    refresh_expires_at: float


_sessions: dict[str, UserTokens] = {}
_sessions_lock = threading.Lock()


def settings() -> TikTokSettings:
    """Read app credentials from the backend environment only."""
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    redirect_uri = os.environ.get("TIKTOK_REDIRECT_URI")
    if not client_key or not client_secret or not redirect_uri:
        raise TikTokConfigurationError("TikTok is not configured.")
    redirect = urlsplit(redirect_uri)
    if redirect.scheme != "https" or not redirect.netloc or redirect.query or redirect.fragment:
        raise TikTokConfigurationError("TikTok redirect URI must be a static HTTPS URL.")
    return TikTokSettings(client_key, client_secret, redirect_uri)


def authorization_url(config: TikTokSettings, state: str) -> str:
    query = urlencode({
        "client_key": config.client_key,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": config.redirect_uri,
        "state": state,
    })
    return f"{AUTHORIZE_URL}?{query}"


def _token_request(config: TikTokSettings, grant: dict[str, str]) -> UserTokens:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(TOKEN_URL, data={
                "client_key": config.client_key,
                "client_secret": config.client_secret,
                **grant,
            })
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("scope"), str):
            raise TikTokError("TikTok did not grant video access.")
        if SCOPE not in payload["scope"].split(","):
            raise TikTokError("TikTok did not grant video access.")
        access_token = payload["access_token"]
        expires_in = int(payload["expires_in"])
        refresh_token = payload.get("refresh_token")
        refresh_expires_in = int(payload.get("refresh_expires_in", 0))
        if not isinstance(access_token, str) or not access_token or expires_in <= 0:
            raise ValueError("Invalid token response")
        if refresh_token is not None and not isinstance(refresh_token, str):
            raise ValueError("Invalid refresh token")
    except TikTokError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise TikTokError("TikTok token request failed.") from None
    now = time.time()
    return UserTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + expires_in,
        refresh_expires_at=now + refresh_expires_in,
    )


def exchange_code(config: TikTokSettings, code: str) -> UserTokens:
    return _token_request(config, {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config.redirect_uri,
    })


def create_session(tokens: UserTokens) -> str:
    """Keep TikTok tokens in process memory, indexed by an opaque cookie."""
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        now = time.time()
        for expired_id, stored in list(_sessions.items()):
            if max(stored.expires_at, stored.refresh_expires_at) <= now:
                del _sessions[expired_id]
        _sessions[session_id] = tokens
    return session_id


def access_token_for_session(session_id: str | None, config: TikTokSettings) -> str:
    if not session_id:
        raise TikTokNotConnected("TikTok account is not connected.")
    with _sessions_lock:
        tokens = _sessions.get(session_id)
        if tokens is None:
            raise TikTokNotConnected("TikTok account is not connected.")
        if tokens.expires_at <= time.time() + 60:
            if not tokens.refresh_token or tokens.refresh_expires_at <= time.time():
                del _sessions[session_id]
                raise TikTokNotConnected("TikTok authorization has expired.")
            refreshed = _token_request(config, {
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
            })
            _sessions[session_id] = refreshed
            tokens = refreshed
        return tokens.access_token


def list_videos(access_token: str, cursor: int | None = None) -> dict:
    """Read one page of public videos and available engagement counts."""
    body = {"max_count": 20}
    if cursor is not None:
        body["cursor"] = cursor
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                VIDEO_LIST_URL,
                params={"fields": ",".join(VIDEO_FIELDS)},
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("error", {}).get("code") != "ok":
            raise TikTokError("TikTok video request failed.")
        data = payload["data"]
        videos = data["videos"]
        if not isinstance(videos, list) or any(not isinstance(item, dict) for item in videos):
            raise ValueError("Invalid video response")
        return {
            "videos": [{field: video[field] for field in VIDEO_FIELDS if field in video}
                       for video in videos],
            "cursor": data.get("cursor"),
            "has_more": bool(data.get("has_more", False)),
        }
    except TikTokError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise TikTokError("TikTok video request failed.") from None


def video_id_from_url(url: str) -> str:
    """Accept a canonical TikTok video URL without following external links."""
    try:
        parsed = urlsplit(url.strip())
        if (parsed.scheme != "https" or parsed.hostname not in
                {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}
                or parsed.username or parsed.password or parsed.port):
            raise ValueError("Invalid TikTok URL")
        match = re.fullmatch(r"/(?:@[^/]+/)?video/([0-9]+)/?", parsed.path)
        if match is None:
            raise ValueError("Invalid TikTok video path")
        return match.group(1)
    except ValueError:
        raise TikTokError("Enter a full TikTok video URL.") from None


def video_performance(access_token: str, video_id: str) -> VideoPerformance:
    """Query one of the authorized user's videos for available counts."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                VIDEO_QUERY_URL,
                params={"fields": ",".join(("id", *PERFORMANCE_FIELDS))},
                headers={"Authorization": f"Bearer {access_token}"},
                json={"filters": {"video_ids": [video_id]}},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("error", {}).get("code") != "ok":
            raise TikTokError("TikTok performance request failed.")
        videos = payload["data"]["videos"]
        if not isinstance(videos, list):
            raise ValueError("Invalid video response")
        match = next((item for item in videos if isinstance(item, dict) and item.get("id") == video_id), None)
        if match is None:
            raise TikTokVideoNotFound("TikTok video was not found for this account.")
        counts = {field: match.get(field) for field in PERFORMANCE_FIELDS}
        if all(value is None for value in counts.values()):
            raise TikTokError("TikTok returned no performance counts.")
        return performance_snapshot("tiktok", counts)
    except TikTokError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise TikTokError("TikTok performance request failed.") from None
