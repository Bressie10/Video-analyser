import hashlib
import hmac
import logging
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi.testclient import TestClient

from app import meta
from app.main import app

CONFIG = {
    "META_APP_ID": "123456", "META_APP_SECRET": "private-app-secret",
    "META_REDIRECT_URI": "https://testserver/api/meta/callback",
    "META_LOGIN_CONFIG_ID": "654321", "META_GRAPH_API_VERSION": "v26.0",
}
TOKEN = "private-user-token"
CODE = "private-oauth-code"


@patch.dict(os.environ, CONFIG)
class MetaAPITests(unittest.TestCase):
    def setUp(self):
        meta._sessions.clear()
        meta._states.clear()
        self.api = TestClient(app, base_url="https://testserver")
        self.outbound = []

    def tearDown(self):
        meta._sessions.clear()
        meta._states.clear()

    def begin(self):
        response = self.api.get("/api/meta/connect", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]

    def respond(self, request):
        self.outbound.append(request)
        if request.url.path == "/v26.0/oauth/access_token":
            return httpx.Response(200, json={
                "access_token": TOKEN, "token_type": "bearer", "expires_in": 3600,
            })
        if request.url.path == "/v26.0/me/permissions":
            return httpx.Response(200, json={
                "data": [{"permission": p, "status": "granted"}
                         for p in meta.PERMISSIONS | {"public_profile"}],
            })
        if request.url.path == "/v26.0/me":
            return httpx.Response(200, json={"id": "123", "access_token": TOKEN})
        return httpx.Response(404)

    def transport(self, respond=None):
        original = httpx.Client
        return patch("app.meta.httpx.Client", side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(respond or self.respond), **kwargs,
        ))

    def callback(self, state):
        return self.api.get("/api/meta/callback", params={"state": state, "code": CODE})

    def test_business_login_configuration_and_cookie(self):
        response = self.api.get("/api/meta/connect", follow_redirects=False)
        query = parse_qs(urlsplit(response.headers["location"]).query)
        self.assertEqual(query["config_id"], [CONFIG["META_LOGIN_CONFIG_ID"]])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["redirect_uri"], [CONFIG["META_REDIRECT_URI"]])
        self.assertNotIn("scope", query)
        for flag in ("Secure", "HttpOnly", "SameSite=lax", "Max-Age=600"):
            self.assertIn(flag, response.headers["set-cookie"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(CONFIG["META_APP_SECRET"], str(response.headers))

    def test_complete_oauth_authenticated_request_and_no_secret_leaks(self):
        state = self.begin()
        with self.transport(), self.assertLogs("httpx", level="DEBUG") as logs:
            callback = self.callback(state)
            checked = self.api.get("/api/meta/test")
        self.assertEqual(callback.status_code, 200)
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(callback.json(), {"connected": True, "user_id": "123"})
        self.assertEqual(checked.json(), callback.json())
        self.assertEqual(len(meta._sessions), 1)
        self.assertEqual(self.outbound[0].url.params["client_secret"], CONFIG["META_APP_SECRET"])
        self.assertEqual(self.outbound[0].url.params["code"], CODE)
        self.assertEqual(self.outbound[0].url.params["redirect_uri"], CONFIG["META_REDIRECT_URI"])
        for request in self.outbound[1:]:
            self.assertEqual(request.headers["authorization"], f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, str(request.url))
            self.assertEqual(request.url.params["appsecret_proof"], hmac.new(
                CONFIG["META_APP_SECRET"].encode(), TOKEN.encode(), hashlib.sha256,
            ).hexdigest())
        self.assertEqual(self.outbound[-1].url.params["fields"], "id")
        # TestClient has separate inbound HTTP logs; Uvicorn is checked below.
        provider_logs = "\n".join(line for line in logs.output if "graph.facebook.com" in line)
        for secret in (TOKEN, CONFIG["META_APP_SECRET"], CODE):
            self.assertNotIn(secret, provider_logs + callback.text + checked.text + str(callback.headers))
        self.assertNotIn(TOKEN, repr(next(iter(meta._sessions.values()))))
        self.assertNotIn(CONFIG["META_APP_SECRET"], repr(meta.settings()))
        self.assertEqual(checked.headers["Referrer-Policy"], "no-referrer")
        self.api.cookies.set(meta.STATE_COOKIE, state, path="/api/meta/callback")
        with self.transport():
            self.assertEqual(self.callback(state).status_code, 400)
        self.assertEqual(len(self.outbound), 4)

    def test_wrong_expired_and_unicode_states_cannot_exchange(self):
        state = self.begin()
        with patch("app.meta.exchange_code") as exchange:
            for bad in ("wrong", "", "☃"):
                self.assertEqual(self.callback(bad).status_code, 400)
            self.api.cookies.set(meta.STATE_COOKIE, state, path="/api/meta/callback")
            with patch("app.meta.time.time", return_value=time.time() + 601):
                self.assertEqual(self.callback(state).status_code, 400)
            exchange.assert_not_called()

    def test_cancellation_consumes_state(self):
        state = self.begin()
        with patch("app.meta.exchange_code") as exchange:
            response = self.api.get("/api/meta/callback", params={"state": state, "error": "access_denied"})
            self.assertEqual(response.status_code, 400)
            exchange.assert_not_called()
        self.assertNotIn(state, meta._states)
        self.assertEqual(meta._sessions, {})

    def test_missing_or_extra_permissions_do_not_create_session(self):
        for permissions in (meta.PERMISSIONS - {"ads_read"}, meta.PERMISSIONS | {"ads_management"}):
            with self.subTest(permissions=permissions):
                state = self.begin()
                def respond(request):
                    if request.url.path.endswith("/permissions"):
                        return httpx.Response(200, json={"data": [
                            {"permission": p, "status": "granted"} for p in permissions
                        ]})
                    return self.respond(request)
                with self.transport(respond):
                    self.assertEqual(self.callback(state).status_code, 403)
                self.assertEqual(meta._sessions, {})

    def test_bad_token_and_provider_responses_are_safe(self):
        for payload in ([], {"access_token": TOKEN}, {"access_token": TOKEN, "expires_in": True},
                        {"error": {"message": TOKEN + CONFIG["META_APP_SECRET"], "code": 100}}):
            with self.subTest(payload=payload):
                state = self.begin()
                with self.transport(lambda request: httpx.Response(200, json=payload)):
                    response = self.callback(state)
                self.assertEqual(response.status_code, 502)
                self.assertNotIn(TOKEN, response.text)
                self.assertNotIn(CONFIG["META_APP_SECRET"], response.text)
                self.assertEqual(meta._sessions, {})

    def test_unauthorized_expired_and_revoked_sessions(self):
        with patch("app.meta._get") as request:
            self.assertEqual(self.api.get("/api/meta/test").status_code, 401)
            expired = meta.create_session(meta.UserToken(TOKEN, time.time() - 1))
            self.api.cookies.set(meta.SESSION_COOKIE, expired, path="/api/meta")
            self.assertEqual(self.api.get("/api/meta/test").status_code, 401)
            request.assert_not_called()
        session = meta.create_session(meta.UserToken(TOKEN, time.time() + 1000))
        self.api.cookies.set(meta.SESSION_COOKIE, session, path="/api/meta")
        with self.transport(lambda request: httpx.Response(400, json={"error": {"code": 190, "message": TOKEN}})):
            response = self.api.get("/api/meta/test")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(session, meta._sessions)
        self.assertNotIn(TOKEN, response.text)

    def test_reauthorization_rotates_session(self):
        old = meta.create_session(meta.UserToken(TOKEN, time.time() + 1000))
        self.api.cookies.set(meta.SESSION_COOKIE, old, path="/api/meta")
        state = self.begin()
        with self.transport():
            self.assertEqual(self.callback(state).status_code, 200)
        self.assertNotIn(old, meta._sessions)
        self.assertEqual(len(meta._sessions), 1)

    def test_client_blocks_external_paths_and_credential_overrides(self):
        client = meta.MetaClient(meta.settings(), meta.UserToken(TOKEN, time.time() + 1000))
        with patch("app.meta.httpx.Client") as http:
            for path in ("https://evil.example", "//evil.example", "../me", "me?access_token=x"):
                with self.assertRaises(meta.MetaError):
                    client.get(path)
            with self.assertRaises(meta.MetaError):
                client.get("me", {"access_token": "override"})
            http.assert_not_called()

    def test_uvicorn_logging_omits_code_and_state(self):
        logger = logging.getLogger("uvicorn.access")
        with self.assertLogs(logger, level="INFO") as logs:
            logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1", "GET",
                        f"/api/meta/callback?code={CODE}&state=private-state", "1.1", 200)
        self.assertNotIn(CODE, logs.output[0])
        self.assertNotIn("private-state", logs.output[0])

    def test_invalid_configuration_fails_before_network(self):
        for key, value in (("META_APP_ID", ""), ("META_APP_SECRET", ""),
                           ("META_LOGIN_CONFIG_ID", ""), ("META_GRAPH_API_VERSION", "../../evil"),
                           ("META_REDIRECT_URI", "http://testserver/api/meta/callback"),
                           ("META_REDIRECT_URI", "https://user:pass@testserver/api/meta/callback"),
                           ("META_REDIRECT_URI", "https://testserver/api/meta/callback?x=1"),
                           ("META_REDIRECT_URI", "https://[invalid/api/meta/callback")):
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                self.assertEqual(self.api.get("/api/meta/connect").status_code, 503)

    def test_identity_error_cannot_report_connected(self):
        state = self.begin()
        def respond(request):
            if request.url.path == "/v26.0/me":
                return httpx.Response(200, json={"id": TOKEN})
            return self.respond(request)
        with self.transport(respond):
            response = self.callback(state)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(meta._sessions, {})

    def test_transport_timeout_redirect_and_non_json_fail_safely(self):
        client = meta.MetaClient(meta.settings(), meta.UserToken(TOKEN, time.time() + 1000))
        def timeout(request):
            raise httpx.ReadTimeout(TOKEN, request=request)
        for responder in (
            timeout,
            lambda request: httpx.Response(302, headers={"location": "https://evil.example"}),
            lambda request: httpx.Response(500, text=TOKEN),
        ):
            with self.subTest(responder=responder), self.transport(responder):
                with self.assertRaises(meta.MetaError) as caught:
                    client.test_connection()
                self.assertNotIn(TOKEN, str(caught.exception))
