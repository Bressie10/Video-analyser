import os
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app import tiktok


CONFIG = {
    "TIKTOK_CLIENT_KEY": "test-client-key",
    "TIKTOK_CLIENT_SECRET": "test-client-secret",
    "TIKTOK_REDIRECT_URI": "https://testserver/api/tiktok/callback",
}
ACCESS_TOKEN = "test-access-token"
REFRESH_TOKEN = "test-refresh-token"


class TikTokAPITests(unittest.TestCase):
    def setUp(self) -> None:
        tiktok._sessions.clear()

    def tearDown(self) -> None:
        tiktok._sessions.clear()

    @patch.dict(os.environ, CONFIG)
    def test_connect_requests_only_video_list_scope(self) -> None:
        client = TestClient(app, base_url="https://testserver")
        response = client.get("/api/tiktok/connect", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        redirect = urlsplit(response.headers["location"])
        self.assertEqual(redirect.netloc, "www.tiktok.com")
        query = parse_qs(redirect.query)
        self.assertEqual(query["scope"], ["video.list"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["redirect_uri"], [CONFIG["TIKTOK_REDIRECT_URI"]])
        self.assertIn("tiktok_oauth_state=", response.headers["set-cookie"])
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("secure", response.headers["set-cookie"].lower())
        self.assertNotIn(CONFIG["TIKTOK_CLIENT_SECRET"], response.headers["location"])

    @patch.dict(os.environ, CONFIG)
    def test_callback_rejects_wrong_state_without_token_exchange(self) -> None:
        client = TestClient(app, base_url="https://testserver")
        client.get("/api/tiktok/connect", follow_redirects=False)
        with patch("app.tiktok.exchange_code") as exchange:
            response = client.get("/api/tiktok/callback?state=wrong&code=code")
        self.assertEqual(response.status_code, 400)
        exchange.assert_not_called()
        self.assertNotIn(ACCESS_TOKEN, response.text)

    @patch.dict(os.environ, CONFIG)
    def test_authorize_then_fetch_videos_without_exposing_tokens(self) -> None:
        outbound = []

        def respond(request: httpx.Request) -> httpx.Response:
            outbound.append(request)
            if request.url.path == "/v2/oauth/token/":
                return httpx.Response(200, json={
                    "access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN,
                    "expires_in": 3600, "refresh_expires_in": 86400,
                    "scope": "video.list", "token_type": "Bearer", "open_id": "owner-id",
                })
            if request.url.path == "/v2/video/list/":
                return httpx.Response(200, json={
                    "data": {"videos": [{"id": "video-1", "title": "Example", "view_count": 120,
                                         "like_count": 12, "comment_count": 3, "share_count": 2,
                                         "access_token": ACCESS_TOKEN}],
                             "cursor": 123, "has_more": False},
                    "error": {"code": "ok", "message": "", "log_id": "log-1"},
                })
            return httpx.Response(404)

        original_client = httpx.Client
        def mock_client(*, timeout: float) -> httpx.Client:
            return original_client(timeout=timeout, transport=httpx.MockTransport(respond))

        client = TestClient(app, base_url="https://testserver")
        connect = client.get("/api/tiktok/connect", follow_redirects=False)
        state = parse_qs(urlsplit(connect.headers["location"]).query)["state"][0]
        with patch("app.tiktok.httpx.Client", side_effect=mock_client):
            callback = client.get(f"/api/tiktok/callback?state={state}&code=auth-code")
            videos = client.get("/api/tiktok/videos")

        self.assertEqual(callback.status_code, 200)
        self.assertEqual(callback.json(), {"connected": True})
        self.assertIn("tiktok_session=", callback.headers.get("set-cookie", ""))
        self.assertNotIn(ACCESS_TOKEN, callback.text)
        self.assertNotIn(REFRESH_TOKEN, callback.text)
        self.assertEqual(videos.status_code, 200)
        self.assertEqual(videos.json(), {
            "videos": [{"id": "video-1", "title": "Example", "view_count": 120,
                        "like_count": 12, "comment_count": 3, "share_count": 2}],
            "cursor": 123, "has_more": False,
        })
        self.assertNotIn(ACCESS_TOKEN, videos.text)
        self.assertEqual(outbound[1].headers["authorization"], f"Bearer {ACCESS_TOKEN}")
        self.assertEqual(dict(outbound[1].url.params)["fields"], ",".join(tiktok.VIDEO_FIELDS))
        self.assertEqual(parse_qs(outbound[0].content.decode())["client_secret"],
                         [CONFIG["TIKTOK_CLIENT_SECRET"]])

    @patch.dict(os.environ, CONFIG)
    def test_expired_token_is_refreshed_on_backend(self) -> None:
        session_id = tiktok.create_session(tiktok.UserTokens(
            ACCESS_TOKEN, REFRESH_TOKEN, time.time() - 1, time.time() + 3600,
        ))
        with patch("app.tiktok._token_request", return_value=tiktok.UserTokens(
            "new-access-token", "new-refresh-token", time.time() + 3600, time.time() + 86400,
        )) as refresh:
            token = tiktok.access_token_for_session(session_id, tiktok.settings())
        self.assertEqual(token, "new-access-token")
        self.assertEqual(tiktok._sessions[session_id].refresh_token, "new-refresh-token")
        self.assertEqual(refresh.call_args.args[1], {
            "grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN,
        })

    @patch.dict(os.environ, CONFIG)
    def test_video_route_requires_server_session(self) -> None:
        response = TestClient(app, base_url="https://testserver").get("/api/tiktok/videos")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "TikTok account is not connected."})

    @patch.dict(os.environ, CONFIG)
    def test_video_provider_error_cannot_expose_token(self) -> None:
        session_id = tiktok.create_session(tiktok.UserTokens(
            ACCESS_TOKEN, REFRESH_TOKEN, time.time() + 3600, time.time() + 86400,
        ))
        client = TestClient(app, base_url="https://testserver")
        client.cookies.set(tiktok.SESSION_COOKIE, session_id, path="/api")
        with patch("app.tiktok.list_videos", side_effect=tiktok.TikTokError(ACCESS_TOKEN)):
            response = client.get("/api/tiktok/videos")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "TikTok request failed."})
        self.assertNotIn(ACCESS_TOKEN, response.text)

    def test_extracts_only_canonical_tiktok_video_ids(self) -> None:
        self.assertEqual(
            tiktok.video_id_from_url("https://www.tiktok.com/@creator/video/123456789?lang=en"),
            "123456789",
        )
        for url in (
            "https://www.tiktok.com.evil.example/@creator/video/123456789",
            "https://vm.tiktok.com/short-code/",
            "http://www.tiktok.com/@creator/video/123456789",
            "https://www.tiktok.com/@creator/photo/123456789",
        ):
            with self.subTest(url=url), self.assertRaises(tiktok.TikTokError):
                tiktok.video_id_from_url(url)

    def test_video_query_returns_only_requested_counts(self) -> None:
        outbound = []

        def respond(request: httpx.Request) -> httpx.Response:
            outbound.append(request)
            return httpx.Response(200, json={
                "data": {"videos": [{"id": "123456789", "view_count": 120,
                                     "like_count": 12, "comment_count": 3,
                                     "share_count": 2, "access_token": ACCESS_TOKEN}]},
                "error": {"code": "ok", "message": "", "log_id": "log-1"},
            })

        original_client = httpx.Client
        with patch("app.tiktok.httpx.Client", side_effect=lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs,
        )):
            counts = tiktok.video_performance(ACCESS_TOKEN, "123456789")

        self.assertEqual(counts["performance_source"], "tiktok")
        self.assertEqual(counts["performance_metrics"], {
            "view_count": 120, "like_count": 12, "comment_count": 3, "share_count": 2,
        })
        self.assertEqual(outbound[0].url.path, "/v2/video/query/")
        self.assertEqual(outbound[0].headers["authorization"], f"Bearer {ACCESS_TOKEN}")
        self.assertEqual(outbound[0].url.params["fields"],
                         "id,view_count,like_count,comment_count,share_count")
        self.assertEqual(json.loads(outbound[0].content),
                         {"filters": {"video_ids": ["123456789"]}})

    @patch.dict(os.environ, {**CONFIG, "DATABASE_URL": "postgresql://test"})
    def test_upload_links_stats_to_internal_video_id(self) -> None:
        session_id = tiktok.create_session(tiktok.UserTokens(
            ACCESS_TOKEN, REFRESH_TOKEN, time.time() + 3600, time.time() + 86400,
        ))
        counts = {"view_count": 120, "like_count": 12, "comment_count": 3, "share_count": 2}
        client = TestClient(app, base_url="https://testserver")
        client.cookies.set(tiktok.SESSION_COOKIE, session_id, path="/api")
        with patch("app.main.tiktok.video_performance", return_value={"performance_source": "tiktok", "performance_metrics": counts}) as fetch, \
             patch("app.main.inspect_video") as inspect, \
             patch("app.main.normalise_video"), \
             patch("app.main.detect_scenes", return_value=[]), \
             patch("app.main.detect_on_screen_text", return_value=[]), \
             patch("app.main.detect_motion_events", return_value=[]), \
             patch("app.main.extract_wav_audio"), \
             patch("app.main.transcribe_audio", return_value={"text": "", "segments": []}), \
             patch("app.main.save_analysis", return_value="internal-uuid") as save:
            inspect.return_value.as_dict.return_value = {"duration_seconds": 5}
            response = client.post(
                "/api/videos",
                files={"video": ("sample.mp4", b"video", "video/mp4")},
                data={"tiktok_url": "https://www.tiktok.com/@creator/video/123456789"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["video_id"], "internal-uuid")
        self.assertEqual(response.json()["performance_metrics"], counts)
        fetch.assert_called_once_with(ACCESS_TOKEN, "123456789")
        saved = save.call_args.args[0]
        self.assertEqual(saved["performance_metrics"], counts)
        self.assertEqual(saved["performance_source"], "tiktok")
        self.assertEqual(response.json()["performance_source"], "tiktok")
        self.assertNotIn("tiktok_url", saved)
        self.assertNotIn("tiktok_video_id", saved)

    @patch.dict(os.environ, {**CONFIG, "DATABASE_URL": "postgresql://test"})
    def test_upload_with_tiktok_url_requires_connection(self) -> None:
        response = TestClient(app, base_url="https://testserver").post(
            "/api/videos",
            files={"video": ("sample.mp4", b"video", "video/mp4")},
            data={"tiktok_url": "https://www.tiktok.com/@creator/video/123456789"},
        )
        self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {**CONFIG, "DATABASE_URL": "postgresql://test"})
    def test_upload_rejects_non_tiktok_url_before_processing(self) -> None:
        with patch("app.main.inspect_video") as inspect:
            response = TestClient(app, base_url="https://testserver").post(
                "/api/videos",
                files={"video": ("sample.mp4", b"video", "video/mp4")},
                data={"tiktok_url": "https://www.tiktok.com.evil.example/@creator/video/123456789"},
            )
        self.assertEqual(response.status_code, 422)
        inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
