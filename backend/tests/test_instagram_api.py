from contextlib import contextmanager
from copy import deepcopy
import os
import time
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx
import psycopg
from fastapi.testclient import TestClient

from app import instagram, meta
from app.main import app
from app.video_repository import PerformanceSourceConflict
from test_meta_api import CONFIG, TOKEN

VIDEO_ID = UUID("8db7e284-353b-4f3e-9bf0-44d78d888720")
MEDIA_ID = "17895695668004550"
MEDIA = {"id": MEDIA_ID, "media_type": "VIDEO", "media_product_type": "REELS"}
COUNTS = {"view_count": 120, "like_count": 12, "comment_count": 0, "share_count": 2}
SNAPSHOT = {"performance_source": "instagram", "performance_metrics": COUNTS}


def insights(values=None):
    values = values if values is not None else {"views": 120, "likes": 12, "comments": 0, "shares": 2}
    return {"data": [
        {"name": name, "period": "lifetime", "values": [{"value": value}],
         "id": f"{MEDIA_ID}/insights/{name}/lifetime"}
        for name, value in values.items()
    ]}


def authenticated_api():
    session = meta.create_session(meta.UserToken(TOKEN, time.time() + 3600))
    api = TestClient(app, base_url="https://testserver")
    api.cookies.set(meta.SESSION_COOKIE, session, path="/api/meta")
    return api


def attach(api, video_id=VIDEO_ID):
    return api.post(f"/api/meta/instagram/reels/{MEDIA_ID}/metrics", json={"video_id": str(video_id)})


@contextmanager
def graph_transport(media=None, metrics=None, error=None):
    requests = []
    original = httpx.Client
    def respond(request):
        requests.append(request)
        if error is not None:
            return httpx.Response(400, json={"error": error})
        if request.url.path == f"/v26.0/{MEDIA_ID}":
            return httpx.Response(200, json=media if media is not None else MEDIA)
        if request.url.path == f"/v26.0/{MEDIA_ID}/insights":
            return httpx.Response(200, json=metrics if metrics is not None else insights())
        raise AssertionError(f"Unexpected Graph path: {request.url.path}")
    with patch("app.meta.httpx.Client", side_effect=lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs,
    )):
        yield requests


@patch.dict(os.environ, CONFIG)
class InstagramAPITests(unittest.TestCase):
    def setUp(self):
        meta._sessions.clear()
        self.api = authenticated_api()

    def tearDown(self):
        meta._sessions.clear()

    def test_fetches_reel_and_stores_common_snapshot_for_exact_uuid(self):
        with patch("app.instagram_routes.get_analysis", return_value={"video_id": str(VIDEO_ID)}) as read, \
             patch("app.instagram_routes.save_performance", return_value=True) as save, graph_transport() as requests:
            response = attach(self.api)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"video_id": str(VIDEO_ID), **SNAPSHOT})
        read.assert_called_once_with(VIDEO_ID)
        save.assert_called_once_with(VIDEO_ID, SNAPSHOT)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].url.params["fields"], "id,media_type,media_product_type")
        self.assertEqual(requests[1].url.params["metric"], "views,likes,comments,shares")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for request in requests:
            self.assertEqual(request.headers["authorization"], f"Bearer {TOKEN}")
            self.assertNotIn(TOKEN, str(request.url))
        self.assertNotIn(TOKEN, response.text)

    def test_partial_counts_remain_null_and_zero_is_preserved(self):
        client = meta.session_client(self.api.cookies.get(meta.SESSION_COOKIE))
        response = insights({"views": 0, "likes": None})
        response["data"].append({"name": "shares", "period": "lifetime", "values": []})
        with graph_transport(metrics=response):
            snapshot = instagram.reel_performance(client, MEDIA_ID)
        self.assertEqual(snapshot["performance_metrics"], {
            "view_count": 0, "like_count": None, "comment_count": None, "share_count": None,
        })

    def test_no_counts_never_write_or_replace_existing_snapshot(self):
        for payload in ({"data": []}, insights({"views": None}), insights({"total_views": 900})):
            with self.subTest(payload=payload), \
                 patch("app.instagram_routes.get_analysis", return_value=SNAPSHOT), \
                 patch("app.instagram_routes.save_performance") as save, graph_transport(metrics=payload):
                self.assertEqual(attach(self.api).status_code, 422)
                save.assert_not_called()

    def test_non_reel_media_is_rejected_before_insights(self):
        for media in ({**MEDIA, "media_product_type": "FEED"}, {**MEDIA, "media_type": "IMAGE"}):
            with self.subTest(media=media), \
                 patch("app.instagram_routes.get_analysis", return_value={}), \
                 patch("app.instagram_routes.save_performance") as save, graph_transport(media=media) as requests:
                self.assertEqual(attach(self.api).status_code, 422)
                self.assertEqual(len(requests), 1)
                save.assert_not_called()

    def test_mismatched_media_id_is_rejected(self):
        with patch("app.instagram_routes.get_analysis", return_value={}), \
             patch("app.instagram_routes.save_performance") as save, graph_transport(media={**MEDIA, "id": "999"}):
            self.assertEqual(attach(self.api).status_code, 502)
            save.assert_not_called()

    def test_malformed_insights_fail_without_saving(self):
        bad_payloads = [{"data": None}, {"data": [None]}, insights({"views": -1}),
                        insights({"views": True}), insights({"views": "120"}), insights({"views": 2**63})]
        duplicate = insights()
        duplicate["data"].append(deepcopy(duplicate["data"][0]))
        bad_payloads.append(duplicate)
        for key, value in (("period", "day"), ("id", "999/insights/views/lifetime"),
                           ("values", [{"value": 1}, {"value": 2}])):
            payload = insights({"views": 1})
            payload["data"][0][key] = value
            bad_payloads.append(payload)
        for payload in bad_payloads:
            with self.subTest(payload=payload), \
                 patch("app.instagram_routes.get_analysis", return_value={}), \
                 patch("app.instagram_routes.save_performance") as save, graph_transport(metrics=payload):
                self.assertEqual(attach(self.api).status_code, 502)
                save.assert_not_called()

    def test_expired_revoked_or_missing_session_cannot_save(self):
        with patch("app.instagram_routes.save_performance") as save:
            meta._sessions.clear()
            self.assertEqual(attach(self.api).status_code, 401)
            self.api = authenticated_api()
            with patch("app.instagram_routes.get_analysis", return_value={}), \
                 graph_transport(error={"code": 190, "message": TOKEN}):
                response = attach(self.api)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(meta._sessions, {})
            self.assertNotIn(TOKEN, response.text)
            save.assert_not_called()

    def test_permission_and_rate_limit_errors_are_not_missing_counts(self):
        for code in (10, 100, 200, 4):
            with self.subTest(code=code), \
                 patch("app.instagram_routes.get_analysis", return_value={}), \
                 patch("app.instagram_routes.save_performance") as save, \
                 graph_transport(error={"code": code, "message": TOKEN}):
                response = attach(self.api)
                self.assertEqual(response.status_code, 403 if code in (10, 200) else 502)
                self.assertNotIn(TOKEN, response.text)
                save.assert_not_called()

    def test_unknown_uuid_and_other_source_do_not_fetch(self):
        for analysis, status in ((None, 404), ({"performance_source": "tiktok"}, 409)):
            with self.subTest(analysis=analysis), \
                 patch("app.instagram_routes.get_analysis", return_value=analysis), \
                 patch("app.instagram_routes.save_performance") as save, \
                 patch("app.instagram.reel_performance") as fetch:
                self.assertEqual(attach(self.api).status_code, status)
                fetch.assert_not_called()
                save.assert_not_called()

    def test_invalid_ids_are_rejected_before_network_or_database(self):
        with patch("app.instagram_routes.get_analysis") as read:
            self.assertEqual(attach(self.api, "not-a-uuid").status_code, 422)
            self.assertEqual(self.api.post("/api/meta/instagram/reels/shortcode/metrics",
                                          json={"video_id": str(VIDEO_ID)}).status_code, 422)
            read.assert_not_called()

    def test_database_failure_and_concurrent_changes_are_reported(self):
        with patch("app.instagram_routes.get_analysis", side_effect=psycopg.OperationalError("private database url")), \
             patch("app.instagram.reel_performance") as fetch:
            response = attach(self.api)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private database url", response.text)
            fetch.assert_not_called()
        for result, error, status in (
            (False, None, 404), (True, PerformanceSourceConflict(), 409),
            (True, psycopg.OperationalError("private database url"), 503),
        ):
            with self.subTest(status=status), \
                 patch("app.instagram_routes.get_analysis", return_value={}), \
                 patch("app.instagram_routes.save_performance", return_value=result, side_effect=error), graph_transport():
                self.assertEqual(attach(self.api).status_code, status)
