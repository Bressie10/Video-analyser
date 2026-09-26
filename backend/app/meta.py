"""Server-side Facebook Login for Business and a small read-only Graph client."""

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx

# Configure exactly these business permissions in the Meta login configuration.
# pages_read_user_content is a documented dependency of instagram_basic.
PERMISSIONS = frozenset({
    "pages_show_list", "pages_read_engagement", "pages_read_user_content",
    "read_insights", "instagram_basic", "instagram_manage_insights", "ads_read",
})
STATE_COOKIE = "meta_oauth_state"
SESSION_COOKIE = "meta_session"
STATE_MAX_AGE = 600


class MetaError(Exception):
    """Safe error without provider payloads, tokens, or request URLs."""


class MetaConfigurationError(MetaError):
    pass


class MetaNotConnected(MetaError):
    pass


class MetaPermissionError(MetaError):
    pass


@dataclass(frozen=True)
class MetaSettings:
    app_id: str
    app_secret: str = field(repr=False)
    redirect_uri: str
    login_config_id: str
    api_version: str


@dataclass(frozen=True)
class UserToken:
    access_token: str = field(repr=False)
    expires_at: float


_sessions: dict[str, UserToken] = {}
_states: dict[str, tuple[float, MetaSettings]] = {}
_lock = threading.Lock()


class _MetaLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx logs full URLs at INFO. The documented token exchange is GET.
        if record.name == "httpx" and isinstance(record.args, tuple):
            record.args = tuple(
                value.copy_with(query=None)
                if isinstance(value, httpx.URL) and value.host == "graph.facebook.com"
                else value for value in record.args
            )
        # Uvicorn's standard access logger otherwise includes OAuth codes/state.
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if str(args[2]).split("?", 1)[0] == "/api/meta/callback":
                args[2] = "/api/meta/callback"
                record.args = tuple(args)
        return True


for _logger in ("httpx", "uvicorn.access"):
    logging.getLogger(_logger).addFilter(_MetaLogFilter())


def settings() -> MetaSettings:
    values = [os.environ.get(key, "").strip() for key in (
        "META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI", "META_LOGIN_CONFIG_ID",
    )]
    if not all(values):
        raise MetaConfigurationError("Meta is not configured.")
    app_id, app_secret, redirect_uri, config_id = values
    version = os.environ.get("META_GRAPH_API_VERSION", "v26.0")
    try:
        parsed = urlsplit(redirect_uri)
        parsed.port  # Validate malformed ports as configuration errors.
    except ValueError:
        raise MetaConfigurationError("Meta configuration is invalid.") from None
    if (not re.fullmatch(r"[0-9]+", app_id) or not re.fullmatch(r"[0-9]+", config_id)
            or not re.fullmatch(r"v[0-9]+\.0", version)
            or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/api/meta/callback"):
        raise MetaConfigurationError("Meta configuration is invalid.")
    return MetaSettings(app_id, app_secret, redirect_uri, config_id, version)


def begin_login(config: MetaSettings) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    with _lock:
        for key, (expires, _) in list(_states.items()):
            if expires <= time.time():
                del _states[key]
        if len(_states) >= 1024:
            raise MetaError("Too many pending Meta logins. Try again later.")
        _states[state] = (time.time() + STATE_MAX_AGE, config)
    query = urlencode({
        "client_id": config.app_id, "redirect_uri": config.redirect_uri,
        "response_type": "code", "config_id": config.login_config_id, "state": state,
    })
    return state, f"https://www.facebook.com/{config.api_version}/dialog/oauth?{query}"


def consume_state(state: str | None, cookie: str | None) -> MetaSettings:
    if not state or not cookie or not hmac.compare_digest(state.encode(), cookie.encode()):
        raise MetaError("Invalid Meta authorization state.")
    with _lock:
        pending = _states.pop(state, None)
    if pending is None or pending[0] <= time.time():
        raise MetaError("Invalid Meta authorization state.")
    return pending[1]


def _get(config: MetaSettings, path: str, params: dict, token: str | None = None) -> dict:
    # Only relative Graph paths chosen by backend code, never arbitrary provider URLs.
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", path):
        raise MetaError("Invalid Meta API path.")
    headers = {}
    query = dict(params)
    if token is not None:
        if any(key in query for key in ("access_token", "client_secret", "appsecret_proof")):
            raise MetaError("Credentials must be supplied by the Meta client.")
        headers["Authorization"] = f"Bearer {token}"
        query["appsecret_proof"] = hmac.new(
            config.app_secret.encode(), token.encode(), hashlib.sha256,
        ).hexdigest()
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            response = client.get(
                f"https://graph.facebook.com/{config.api_version}/{path}",
                params=query, headers=headers,
            )
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                if payload["error"].get("code") == 190:
                    raise MetaNotConnected("Meta authorization expired or was revoked. Connect again.")
                raise MetaError("Meta API request failed.")
            response.raise_for_status()
            if not isinstance(payload, dict):
                raise ValueError("Invalid response")
            return payload
    except MetaError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise MetaError("Meta API request failed.") from None


def exchange_code(config: MetaSettings, code: str) -> UserToken:
    payload = _get(config, "oauth/access_token", {
        "client_id": config.app_id, "client_secret": config.app_secret,
        "redirect_uri": config.redirect_uri, "code": code,
    })
    token, expires = payload.get("access_token"), payload.get("expires_in")
    if (not isinstance(token, str) or not token or any(char.isspace() for char in token)
            or type(expires) is not int or expires <= 0
            or str(payload.get("token_type", "")).lower() != "bearer"):
        raise MetaError("Meta returned an invalid user token.")
    return UserToken(token, time.time() + expires)


class MetaClient:
    def __init__(self, config: MetaSettings, token: UserToken):
        self._config = config
        self._token = token

    def get(self, path: str, params: dict | None = None) -> dict:
        if self._token.expires_at <= time.time():
            raise MetaNotConnected("Meta authorization expired. Connect again.")
        return _get(self._config, path, params or {}, self._token.access_token)

    def verify_permissions(self) -> None:
        rows = self.get("me/permissions", {"limit": 100}).get("data")
        if not isinstance(rows, list):
            raise MetaError("Meta returned an invalid permissions response.")
        granted = {row.get("permission") for row in rows if isinstance(row, dict)
                   and row.get("status") == "granted" and isinstance(row.get("permission"), str)}
        if not PERMISSIONS <= granted:
            raise MetaPermissionError("Required Meta permissions were not granted. Check the login configuration.")
        if granted - PERMISSIONS - {"public_profile", "email"}:
            raise MetaPermissionError("Meta granted unexpected permissions. Use the documented read-only configuration.")

    def test_connection(self) -> dict:
        payload = self.get("me", {"fields": "id"})
        user_id = payload.get("id")
        if not isinstance(user_id, str) or not re.fullmatch(r"[0-9]+", user_id):
            raise MetaError("Meta returned an invalid identity response.")
        return {"connected": True, "user_id": user_id}


def create_session(token: UserToken, previous: str | None = None) -> str:
    session_id = secrets.token_urlsafe(32)
    with _lock:
        for key, stored in list(_sessions.items()):
            if stored.expires_at <= time.time() or key == previous:
                del _sessions[key]
        _sessions[session_id] = token
    return session_id


def session_client(session_id: str | None) -> MetaClient:
    with _lock:
        token = _sessions.get(session_id)
        if token is None or token.expires_at <= time.time():
            _sessions.pop(session_id, None)
            raise MetaNotConnected("Meta account is not connected. Connect again.")
    return MetaClient(settings(), token)


def remove_session(session_id: str | None) -> None:
    with _lock:
        _sessions.pop(session_id, None)
