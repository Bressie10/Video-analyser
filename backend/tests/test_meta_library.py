"""Library policy and actual PostgreSQL migration/worker/API integration tests."""

import os
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import psycopg
from app import instagram, meta
from app import meta_library_repository as repo
from app import meta_library_worker as worker
from app.main import app
from app.meta_library_discovery import creative_video_ids, page, timestamp
from app.meta_library_routes import recommendation_evidence
from app.meta_media import MediaUnavailable, download, validate_url
from app.video_repository import get_analysis, save_analysis
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from test_meta_api import CONFIG
from test_recommendations_api import ANALYSIS


class LibraryPolicyTests(unittest.TestCase):
    def test_age_boundary_and_missing_publication(self):
        at = repo.now()
        self.assertTrue(repo.recent(at - timedelta(days=90) + timedelta(seconds=1), at))
        self.assertFalse(repo.recent(at - timedelta(days=90), at))
        self.assertFalse(repo.recent(None, at))
        self.assertFalse(repo.recent(at + timedelta(seconds=1), at))

    def test_timestamp_requires_timezone(self):
        self.assertIsNone(timestamp("2026-01-01"))
        self.assertIsNone(timestamp("bad"))
        self.assertEqual(timestamp("2026-01-01T00:00:00Z").utcoffset(), timedelta(0))

    def test_explicit_creative_assets_deduplicate(self):
        self.assertEqual(
            creative_video_ids(
                {
                    "video_id": "12",
                    "object_story_spec": {"video_data": {"video_id": "12"}},
                    "asset_feed_spec": {"videos": [{"video_id": "13"}]},
                }
            ),
            ["12", "13"],
        )
        self.assertEqual(
            creative_video_ids({"id": "123", "effective_object_story_id": "4_5"}), []
        )

    def test_pagination_never_follows_provider_url(self):
        class Client:
            def get(self, path, params):
                return {
                    "data": [],
                    "paging": {
                        "next": "https://evil.invalid/?access_token=secret",
                        "cursors": {"after": "next"},
                    },
                }

        self.assertEqual(page(Client(), "me/accounts", "id"), ([], "next"))
        with self.assertRaises(meta.MetaError):
            page(Client(), "me/accounts", "id", "next")

    def test_downloader_blocks_non_meta_and_private_destinations(self):
        for url in (
            "http://x.fbcdn.net/video",
            "https://evil.invalid/video",
            "https://user:pass@x.fbcdn.net/video",
            "https://x.fbcdn.net:8080/video",
            "https://fbcdn.net.evil.invalid/video",
        ):
            with self.assertRaises(MediaUnavailable):
                validate_url(url)
        with patch(
            "app.meta_media.socket.getaddrinfo",
            return_value=[(0, 0, 0, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaises(MediaUnavailable):
                validate_url("https://x.fbcdn.net/video")

    def test_downloader_bounds_and_redirects(self):
        original = httpx.Client
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory, "source.mp4")
            for response in (
                httpx.Response(200, headers={"content-length": "999999999"}),
                httpx.Response(302, headers={"location": "https://evil.invalid/video"}),
            ):
                with (
                    patch(
                        "app.meta_media.socket.getaddrinfo",
                        return_value=[(0, 0, 0, "", ("8.8.8.8", 443))],
                    ),
                    patch(
                        "app.meta_media.httpx.Client",
                        side_effect=lambda **kw: original(
                            transport=httpx.MockTransport(lambda r: response), **kw
                        ),
                    ),
                ):
                    with self.assertRaises(MediaUnavailable):
                        download("https://x.fbcdn.net/video", destination)


class GraphFixture:
    def __init__(self):
        self.recent = (repo.now() - timedelta(days=1)).isoformat()
        self.old = (repo.now() - timedelta(days=100)).isoformat()
        self.videos = [
            {"id": "100", "title": "Facebook video", "created_time": self.recent},
            {"id": "101", "title": "History", "created_time": self.old},
        ]
        self.reels = [
            {"id": "102", "title": "Facebook Reel", "created_time": self.recent}
        ]
        self.instagram = [
            {
                "id": "200",
                "caption": "IG Reel",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "timestamp": self.recent,
            }
        ]
        self.ads = [
            {
                "id": "300",
                "name": "Video ad",
                "created_time": self.recent,
                "creative": {"video_id": "400"},
            }
        ]
        self.calls = []
        self.unavailable = set()
        self.fail_edges = set()

    def for_page(self, page_id):
        return self

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path in self.fail_edges:
            raise meta.MetaError("Provider failure with secret external information")
        lists = {
            "me/accounts": [{"id": "1", "name": "Page"}],
            "me/adaccounts": [
                {"id": "act_3", "name": "Ads", "timezone_name": "Europe/Dublin"}
            ],
            "1/videos": self.videos,
            "1/video_reels": self.reels,
            "2/media": self.instagram,
            "act_3/ads": self.ads,
        }
        if path in lists:
            return {"data": deepcopy(lists[path])}
        if path.endswith("/insights") or path.endswith("/video_insights"):
            return {"data": []}
        if path == "1":
            return {"instagram_business_account": {"id": "2", "name": "Instagram"}}
        if params and "created_time" in params.get("fields", ""):
            return {"id": path, "created_time": self.recent}
        if path.isdigit():
            return {
                "id": path,
                **(
                    {}
                    if path in self.unavailable
                    else {
                        "source": "https://x.fbcdn.net/video",
                        "media_url": "https://x.cdninstagram.com/video",
                    }
                ),
            }
        raise AssertionError((path, params))


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL"
)
class MetaLibraryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.schema = "meta_library_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.admin.execute(f"CREATE SCHEMA {self.schema}")
        self.url = make_conninfo(
            os.environ["TEST_DATABASE_URL"], options=f"-csearch_path={self.schema}"
        )
        self.env = patch.dict(
            os.environ,
            {
                **CONFIG,
                "DATABASE_URL": self.url,
                "META_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "META_WORKER_ENABLED": "false",
            },
        )
        self.env.start()
        with repo.database() as db:
            for migration in sorted(
                (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
            ):
                db.execute(migration.read_text())
        self.graph = GraphFixture()
        self.client_patch = patch(
            "app.meta_library_repository.connection_client", return_value=self.graph
        )
        self.client_patch.start()
        self.session, self.run_id = repo.connect_identity(
            "123", meta.UserToken("private-token", time.time() + 86400 * 30)
        )
        self.connection_id = repo.session_connection(self.session)["id"]
        self.api = TestClient(app, base_url="https://testserver")
        self.api.cookies.set(meta.SESSION_COOKIE, self.session, path="/api/meta")
        self.analysis = patch(
            "app.meta_library_worker.analyze_file", return_value=deepcopy(ANALYSIS)
        ).start()
        self.download = patch("app.meta_library_worker.download").start()
        snapshot = {
            "performance_source": "facebook",
            "performance_metrics": {
                "view_count": 100,
                "like_count": 10,
                "comment_count": 2,
                "share_count": 1,
            },
        }
        self.fb = patch(
            "app.meta_library_worker.facebook.video_performance",
            return_value=deepcopy(snapshot),
        ).start()
        self.ig = patch(
            "app.meta_library_worker.instagram.reel_performance",
            return_value={**snapshot, "performance_source": "instagram"},
        ).start()
        self.ad = patch(
            "app.meta_library_worker.meta_ads.ad_performance",
            return_value={**snapshot, "performance_source": "meta_ads"},
        ).start()

    def tearDown(self):
        patch.stopall()
        self.admin.execute(f"DROP SCHEMA {self.schema} CASCADE")
        self.admin.close()

    def drain(self):
        for _ in range(500):
            with repo.database() as db:
                db.execute(
                    "UPDATE meta_jobs SET available_at=now() WHERE state='queued'"
                )
                repo.finalize_runs(db)
            job = worker.claim_job(False) or worker.claim_job(True)
            if job is None:
                with repo.database() as db:
                    repo.finalize_runs(db)
                    queued = db.execute(
                        "SELECT count(*) AS n FROM meta_jobs WHERE state='queued'"
                    ).fetchone()["n"]
                if not queued:
                    return
            else:
                worker.process_job(job)
        self.fail("Queue did not drain")

    def item(self, external_id):
        with repo.database() as db:
            return db.execute(
                "SELECT * FROM meta_library_items WHERE external_id=%s", (external_id,)
            ).fetchone()

    def sync_again(self):
        response = self.api.post("/api/meta/sync")
        self.assertEqual(response.status_code, 202, response.text)
        self.drain()
        return response.json()["job_id"]

    def test_first_sync_instagram_facebook_reel_and_ad(self):
        self.drain()
        for external_id in ("100", "102", "200", "400"):
            item = self.item(external_id)
            self.assertEqual(item["analysis_state"], "completed", item)
            self.assertEqual(item["analysis_version"], 1)
            self.assertEqual(
                get_analysis(item["video_id"], connection_id=self.connection_id)[
                    "audio"
                ],
                ANALYSIS["audio"],
            )
        self.assertEqual(self.item("101")["analysis_state"], "deferred")
        self.assertEqual(self.analysis.call_count, 4)
        self.assertEqual(self.fb.call_count, 2)
        self.assertEqual(self.ig.call_count, 1)
        self.assertEqual(self.ad.call_count, 1)
        response = self.api.get("/api/meta/library")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 6)
        for forbidden in (
            "external_id",
            "page_external_id",
            "private-token",
            "token_ciphertext",
            "https://x.fbcdn",
        ):
            self.assertNotIn(forbidden, response.text)
        status = self.api.get("/api/meta/jobs/" + self.run_id).json()
        self.assertEqual(status["state"], "completed", status)

    def test_repeated_sync_reuses_analysis_but_refreshes_recent_metrics(self):
        self.drain()
        before = self.item("100")["video_id"]
        self.analysis.reset_mock()
        self.download.reset_mock()
        self.fb.reset_mock()
        self.sync_again()
        self.assertEqual(self.item("100")["video_id"], before)
        self.analysis.assert_not_called()
        self.download.assert_not_called()
        self.assertEqual(self.fb.call_count, 2)
        with repo.database() as db:
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM meta_library_items").fetchone()[
                    "n"
                ],
                6,
            )
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM videos").fetchone()["n"], 4
            )

    def test_new_source_is_automatically_analyzed(self):
        self.drain()
        self.graph.videos.append(
            {"id": "103", "created_time": repo.now().isoformat(), "title": "New upload"}
        )
        self.analysis.reset_mock()
        self.sync_again()
        self.assertEqual(self.item("103")["analysis_state"], "completed")
        self.analysis.assert_called_once()
        self.sync_again()
        self.analysis.assert_called_once()

    def test_version_change_replaces_analysis_atomically_and_preserves_uuid(self):
        self.drain()
        before = self.item("100")["video_id"]
        self.analysis.reset_mock()
        with patch.object(repo, "ANALYSIS_VERSION", 2):
            self.sync_again()
        self.assertEqual(self.item("100")["video_id"], before)
        self.assertEqual(self.item("100")["analysis_version"], 2)
        self.assertEqual(self.analysis.call_count, 4)
        with repo.database() as db:
            self.assertEqual(
                db.execute(
                    "SELECT analysis_version FROM videos WHERE id=%s", (before,)
                ).fetchone()["analysis_version"],
                2,
            )
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM videos").fetchone()["n"], 4
            )
        self.assertIsNone(self.item("101")["video_id"])

    def test_old_metrics_retained_and_manual_refresh(self):
        self.drain()
        item = self.item("100")
        with repo.database() as db:
            before = db.execute(
                "SELECT * FROM meta_library_performance WHERE item_id=%s", (item["id"],)
            ).fetchone()
            db.execute(
                "UPDATE meta_library_items SET published_at=now()-interval '100 days' WHERE id=%s",
                (item["id"],),
            )
        self.graph.videos[0]["created_time"] = self.graph.old
        self.fb.reset_mock()
        self.analysis.reset_mock()
        self.sync_again()
        self.assertEqual(self.fb.call_count, 1)  # Only the recent Facebook Reel.
        with repo.database() as db:
            self.assertEqual(
                db.execute(
                    "SELECT * FROM meta_library_performance WHERE item_id=%s",
                    (item["id"],),
                ).fetchone(),
                before,
            )
        response = self.api.post(
            "/api/meta/library/metrics/refresh", json={"item_ids": [str(item["id"])]}
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.drain()
        self.assertEqual(self.fb.call_count, 2)
        self.analysis.assert_not_called()

    def test_initial_limit_does_not_drain_backlog(self):
        self.graph.videos = [
            {"id": str(1000 + i), "created_time": self.graph.recent} for i in range(40)
        ]
        self.drain()
        self.assertEqual(self.analysis.call_count, 25)
        self.sync_again()
        self.assertEqual(self.analysis.call_count, 25)
        with repo.database() as db:
            item = db.execute(
                "SELECT id FROM meta_library_items WHERE analysis_state='deferred' LIMIT 1"
            ).fetchone()
        result = self.api.post(
            "/api/meta/library/analyze", json={"item_ids": [str(item["id"])]}
        )
        self.assertEqual(result.status_code, 202, result.text)
        self.drain()
        self.assertEqual(self.analysis.call_count, 26)

    def test_batch_partial_failure_and_unavailable_media(self):
        self.graph.unavailable.add("100")
        self.drain()
        self.assertEqual(self.item("100")["analysis_state"], "unavailable")
        self.assertEqual(self.item("200")["analysis_state"], "completed")
        self.assertEqual(
            self.api.get("/api/meta/jobs/" + self.run_id).json()["state"],
            "partial_failure",
        )
        self.graph.unavailable.clear()
        result = self.api.post(
            "/api/meta/library/analyze",
            json={
                "item_ids": [
                    str(self.item("100")["id"]),
                    str(self.item("101")["id"]),
                    str(self.item("200")["id"]),
                ]
            },
        )
        self.assertEqual(result.status_code, 202, result.text)
        self.drain()
        for identity in ("100", "101", "200"):
            self.assertEqual(self.item(identity)["analysis_state"], "completed")
        self.assertGreaterEqual(
            self.api.get("/api/meta/jobs/" + result.json()["job_id"])
            .json()["counts"]
            .get("reused", 0),
            1,
        )

    def test_two_ads_and_organic_video_share_one_analysis(self):
        self.graph.ads = [
            {
                "id": str(i),
                "created_time": self.graph.recent,
                "creative": {"video_id": "100"},
            }
            for i in (300, 301)
        ]
        self.drain()
        self.assertEqual(
            self.analysis.call_count, 3
        )  # FB video, Reel, Instagram; no duplicate ad asset.
        response = self.api.get("/api/meta/library/" + str(self.item("100")["id"]))
        self.assertEqual(len(response.json()["performance"]), 3, response.text)

    def test_ad_without_accessible_creative_is_retained(self):
        self.graph.ads[0]["creative"] = {}
        self.drain()
        self.assertEqual(self.item("300")["analysis_state"], "unavailable")
        self.assertEqual(self.item("300")["metrics_state"], "current")

    def test_multi_video_recommendation_uses_stored_evidence_once(self):
        self.drain()
        ids = [str(self.item(i)["id"]) for i in ("100", "200", "400")]
        self.analysis.reset_mock()
        self.download.reset_mock()
        with patch(
            "app.meta_library_routes.recommend_videos",
            return_value={"model": "test", "response": "One idea and script"},
        ) as recommend:
            response = self.api.post(
                "/api/meta/recommendations",
                json={"video_ids": [*ids, ids[0]]},
                headers={"X-OpenAI-API-Key": "request-only"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        evidence = recommend.call_args.args[0]
        self.assertEqual(len(evidence["videos"]), 3)
        self.assertEqual(
            {
                s["snapshot"]["performance_source"]
                for s in evidence["performance_snapshots"]
            },
            {"facebook", "instagram", "meta_ads"},
        )
        self.assertEqual(recommend.call_args.kwargs, {"api_key": "request-only"})
        self.analysis.assert_not_called()
        self.download.assert_not_called()
        with repo.database() as db:
            self.assertNotIn(
                "request-only",
                str(db.execute("SELECT * FROM meta_connections").fetchall()),
            )

    def test_invalid_incomplete_and_foreign_selection(self):
        self.drain()
        response = self.api.post(
            "/api/meta/recommendations",
            json={"video_ids": [str(self.item("101")["id"])]},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            self.api.post(
                "/api/meta/recommendations", json={"video_ids": []}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.api.post(
                "/api/meta/recommendations", json={"video_ids": [str(uuid4())]}
            ).status_code,
            404,
        )
        other, _ = repo.connect_identity(
            "999", meta.UserToken("other-secret", time.time() + 1000)
        )
        self.api.cookies.set(meta.SESSION_COOKIE, other, path="/api/meta")
        self.assertEqual(
            self.api.get(
                "/api/meta/library/" + str(self.item("100")["id"])
            ).status_code,
            404,
        )
        self.assertEqual(self.api.get("/api/meta/jobs/" + self.run_id).status_code, 404)

    def test_encryption_restart_reconnection_and_disconnect(self):
        self.drain()
        with repo.database() as db:
            stored = db.execute(
                "SELECT token_ciphertext FROM meta_connections"
            ).fetchone()["token_ciphertext"]
            session_row = db.execute("SELECT token_hash FROM meta_sessions").fetchone()[
                "token_hash"
            ]
        self.assertNotIn("private-token", stored)
        self.assertNotEqual(session_row, self.session)
        self.assertEqual(repo.cipher().decrypt(stored.encode()), b"private-token")
        meta._sessions.clear()
        self.assertEqual(
            repo.session_connection(self.session)["id"], self.connection_id
        )
        renewed, _ = repo.connect_identity(
            "123", meta.UserToken("renewed", time.time() + 1000), self.session
        )
        self.assertEqual(repo.session_connection(renewed)["id"], self.connection_id)
        with self.assertRaises(meta.MetaNotConnected):
            repo.session_connection(self.session)
        self.api.cookies.set(meta.SESSION_COOKIE, renewed, path="/api/meta")
        self.assertEqual(self.api.post("/api/meta/disconnect").status_code, 200)
        with repo.database() as db:
            self.assertIsNone(
                db.execute("SELECT token_ciphertext FROM meta_connections").fetchone()[
                    "token_ciphertext"
                ]
            )
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM videos").fetchone()["n"], 4
            )

    def test_sync_idempotency_and_interrupted_claim(self):
        self.assertEqual(self.api.post("/api/meta/sync").json()["job_id"], self.run_id)
        job = worker.claim_job(False)
        with repo.database() as db:
            db.execute(
                "UPDATE meta_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",
                (job["id"],),
            )
        replacement = worker.claim_job(False)
        self.assertEqual(job["id"], replacement["id"])
        worker.finish(job, "completed")
        with repo.database() as db:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM meta_jobs WHERE id=%s", (job["id"],)
                ).fetchone()["state"],
                "running",
            )
        worker.process_job(replacement)
        self.drain()
        self.assertEqual(self.analysis.call_count, 4)

    def test_failed_refresh_preserves_snapshot(self):
        self.drain()
        item = self.item("100")
        with repo.database() as db:
            before = db.execute(
                "SELECT * FROM meta_library_performance WHERE item_id=%s", (item["id"],)
            ).fetchone()
        self.fb.side_effect = meta.MetaError("secret payload")
        self.sync_again()
        with repo.database() as db:
            self.assertEqual(
                db.execute(
                    "SELECT * FROM meta_library_performance WHERE item_id=%s",
                    (item["id"],),
                ).fetchone(),
                before,
            )
        self.assertEqual(self.item("100")["metrics_state"], "failed")

    def test_version_failure_keeps_previous_analysis(self):
        self.drain()
        item = self.item("100")
        before = get_analysis(item["video_id"], connection_id=self.connection_id)
        self.analysis.side_effect = RuntimeError("Processing failure")
        with patch.object(repo, "ANALYSIS_VERSION", 2):
            self.sync_again()
        self.assertEqual(
            get_analysis(item["video_id"], connection_id=self.connection_id), before
        )
        self.assertEqual(self.item("100")["analysis_version"], 1)

    def test_imported_analysis_cannot_escape_through_legacy_routes(self):
        self.drain()
        video_id = self.item("100")["video_id"]
        self.assertIsNone(get_analysis(video_id))
        self.assertEqual(
            self.api.get(f"/api/videos/{video_id}/analysis").status_code, 404
        )
        self.assertEqual(
            self.api.post(f"/api/videos/{video_id}/recommendations").status_code, 404
        )
        self.assertEqual(
            self.api.post(
                "/api/meta/facebook/videos/100/metrics",
                json={"video_id": str(video_id), "page_id": "1"},
            ).status_code,
            404,
        )

    def test_multiple_asset_ad_evidence_is_shared_and_not_duplicated(self):
        self.graph.ads[0]["creative"] = {
            "asset_feed_spec": {"videos": [{"video_id": "400"}, {"video_id": "401"}]}
        }
        self.drain()
        evidence = recommendation_evidence(
            self.connection_id, [self.item("400")["id"], self.item("401")["id"]]
        )
        self.assertEqual(len(evidence["performance_snapshots"]), 1)
        self.assertEqual(
            evidence["performance_snapshots"][0]["attribution"], "shared_ad"
        )
        self.assertEqual(
            evidence["videos"][0]["performance_ids"],
            evidence["videos"][1]["performance_ids"],
        )
        ad = self.api.get("/api/meta/library/" + str(self.item("300")["id"])).json()
        self.assertEqual(ad["analysis_state"], "completed")

    def test_overlap_batches_follow_existing_task(self):
        self.drain()
        selected = str(self.item("101")["id"])
        first = self.api.post(
            "/api/meta/library/analyze", json={"item_ids": [selected]}
        ).json()["job_id"]
        second = self.api.post(
            "/api/meta/library/analyze", json={"item_ids": [selected]}
        ).json()["job_id"]
        self.analysis.reset_mock()
        self.drain()
        self.analysis.assert_called_once()
        for run in (first, second):
            result = self.api.get("/api/meta/jobs/" + run).json()
            self.assertEqual(result["state"], "completed", result)
            self.assertEqual(result["items"][0]["item_id"], selected)

    def test_daily_scheduler_does_not_sync_early(self):
        self.drain()
        worker.schedule()
        with repo.database() as db:
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM meta_sync_runs").fetchone()["n"],
                1,
            )
            db.execute(
                "UPDATE meta_connections SET next_sync_at=now()-interval '1 second'"
            )
        worker.schedule()
        with repo.database() as db:
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM meta_sync_runs").fetchone()["n"],
                2,
            )

    def test_revocation_blocks_remaining_work_and_reconnect_resumes(self):
        job = worker.claim_job(False)
        self.graph.fail_edges.add("me/accounts")
        with patch.object(
            self.graph, "get", side_effect=meta.MetaNotConnected("expired")
        ):
            worker.process_job(job)
        worker.schedule()
        with repo.database() as db:
            self.assertEqual(
                db.execute("SELECT status FROM meta_connections").fetchone()["status"],
                "reconnect_required",
            )
        self.assertIsNone(worker.claim_job(False))
        self.graph.fail_edges.clear()
        repo.connect_identity("123", meta.UserToken("new-token", time.time() + 10000))
        self.drain()
        self.assertEqual(self.item("100")["analysis_state"], "completed")

    def test_failed_discovery_retries_without_losing_other_accounts(self):
        self.graph.fail_edges.add("1/videos")
        self.drain()
        self.assertEqual(self.item("200")["analysis_state"], "completed")
        self.assertEqual(self.item("400")["analysis_state"], "completed")
        self.assertEqual(
            self.api.get("/api/meta/jobs/" + self.run_id).json()["state"],
            "partial_failure",
        )
        self.graph.fail_edges.clear()
        self.sync_again()
        self.assertEqual(self.item("100")["analysis_state"], "completed")

    def test_replacement_transaction_rolls_back_children_on_invalid_result(self):
        self.drain()
        item = self.item("100")
        before = get_analysis(item["id"], connection_id=self.connection_id)
        broken = deepcopy(ANALYSIS)
        broken["scenes"][0]["end_seconds"] = -1
        with self.assertRaises(psycopg.IntegrityError), repo.database() as db:
            save_analysis(
                broken, connection=db, video_id=item["id"], analysis_version=2
            )
        self.assertEqual(
            get_analysis(item["id"], connection_id=self.connection_id), before
        )

    def test_oauth_callback_persists_and_enqueues_sync(self):
        # Exercise real OAuth transport, encryption, DB writes, and the public callback.
        from urllib.parse import parse_qs, urlsplit

        original = httpx.Client

        def graph(request):
            if request.url.path.endswith("/oauth/access_token"):
                return httpx.Response(
                    200,
                    json={
                        "access_token": "oauth-private",
                        "token_type": "bearer",
                        "expires_in": 86400 * 30,
                    },
                )
            if request.url.path.endswith("/me/permissions"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"permission": p, "status": "granted"}
                            for p in meta.PERMISSIONS
                        ]
                    },
                )
            return httpx.Response(200, json={"id": "123"})

        login = self.api.get("/api/meta/connect", follow_redirects=False)
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        with patch(
            "app.meta.httpx.Client",
            side_effect=lambda **kw: original(
                transport=httpx.MockTransport(graph), **kw
            ),
        ):
            response = self.api.get(
                "/api/meta/callback", params={"state": state, "code": "private-code"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["connected"])
        self.assertEqual(response.json()["job_id"], self.run_id)
        self.assertNotIn("oauth-private", response.text + str(response.headers))

    def test_recommendations_reject_oversized_evidence(self):
        self.drain()
        identity = self.item("100")["id"]
        with repo.database() as db:
            db.execute(
                "UPDATE videos SET transcript_text=%s WHERE id=%s",
                ("x" * (1024 * 1024), identity),
            )
        with patch("app.meta_library_routes.recommend_videos") as recommend:
            self.assertEqual(
                self.api.post(
                    "/api/meta/recommendations", json={"video_ids": [str(identity)]}
                ).status_code,
                413,
            )
        recommend.assert_not_called()

    def test_inaccessible_post_creative_keeps_ad_and_metrics(self):
        self.graph.ads[0]["creative"] = {"effective_object_story_id": "1_555"}
        self.graph.fail_edges.add("1_555")
        self.drain()
        item = self.item("300")
        self.assertIsNotNone(item)
        self.assertEqual(item["analysis_state"], "unavailable")
        self.assertEqual(item["metrics_state"], "current")

    def test_inaccessible_asset_metadata_has_explicit_state(self):
        self.graph.fail_edges.add("400")
        self.drain()
        self.assertEqual(self.item("400")["analysis_state"], "unavailable")
        response = self.api.get("/api/meta/library/" + str(self.item("300")["id"]))
        self.assertEqual(
            response.json()["analysis_state"], "unavailable", response.text
        )
        self.assertEqual(self.item("300")["metrics_state"], "current")

    def test_optional_reach_can_be_saved_without_engagement(self):
        self.ig.side_effect = instagram.InstagramMetricsUnavailable("No engagement")
        with patch(
            "app.meta_library_metrics.exposure_metrics", return_value={"reach": 500}
        ):
            self.drain()
        item = self.item("200")
        self.assertEqual(item["metrics_state"], "current")
        result = self.api.get("/api/meta/library/" + str(item["id"])).json()[
            "performance"
        ][0]["snapshot"]
        self.assertEqual(result["performance_metrics"]["reach"], 500)
        self.assertIsNone(result["performance_metrics"]["view_count"])

    def test_new_account_initial_history_is_bounded(self):
        self.drain()
        original = self.graph.get

        def get(path, params=None):
            if path == "me/accounts":
                return {
                    "data": [
                        {"id": "1", "name": "Existing"},
                        {"id": "7", "name": "New Page"},
                    ]
                }
            if path == "7":
                return {}
            if path == "7/video_reels":
                return {"data": []}
            if path == "7/videos":
                return {
                    "data": [
                        {"id": str(7000 + i), "created_time": self.graph.recent}
                        for i in range(40)
                    ]
                }
            return original(path, params)

        self.analysis.reset_mock()
        with patch.object(self.graph, "get", side_effect=get):
            self.sync_again()
            self.assertEqual(self.analysis.call_count, 25)
            self.sync_again()
        self.assertEqual(self.analysis.call_count, 25)

    def test_discovery_pagination_resumes_cursor(self):
        original = self.graph.get
        cursors = []

        def get(path, params=None):
            if path == "1/videos":
                after = params.get("after")
                cursors.append(after)
                if after is None:
                    return {
                        "data": [self.graph.videos[0]],
                        "paging": {
                            "next": "https://ignored.invalid",
                            "cursors": {"after": "page2"},
                        },
                    }
                return {"data": [self.graph.videos[1]]}
            return original(path, params)

        with patch.object(self.graph, "get", side_effect=get):
            self.drain()
        self.assertEqual(cursors, [None, "page2"])
        self.assertEqual(self.item("100")["analysis_state"], "completed")
        self.assertEqual(self.item("101")["analysis_state"], "deferred")

    def test_lifespan_workers_complete_sync_with_global_slots(self):
        with patch.dict(os.environ, {"META_WORKER_ENABLED": "true"}):
            with TestClient(app), TestClient(app):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    with repo.database() as db:
                        done = db.execute(
                            "SELECT finished_at FROM meta_sync_runs WHERE id=%s",
                            (self.run_id,),
                        ).fetchone()["finished_at"]
                    if done:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(done, "Lifespan workers did not complete the sync")
        self.assertEqual(self.analysis.call_count, 4)
        self.assertEqual(self.item("100")["analysis_state"], "completed")

    def test_one_inaccessible_ad_asset_does_not_block_other_assets(self):
        self.graph.ads.append(
            {
                "id": "301",
                "created_time": self.graph.recent,
                "creative": {"video_id": "401"},
            }
        )
        self.graph.fail_edges.add("400")
        self.drain()
        self.assertEqual(self.item("400")["analysis_state"], "unavailable")
        self.assertEqual(self.item("401")["analysis_state"], "completed")

    @unittest.skipUnless(
        os.environ.get("RUN_MEDIA_INTEGRATION") == "1",
        "requires local OCR/Whisper models",
    )
    def test_real_media_sync_storage_library_and_recommendation_evidence(self):
        from app.analysis_pipeline import analyze_file
        from app.meta_media import download
        from test_meta_media_pipeline import MediaPipelineTests

        MediaPipelineTests.setUpClass()
        try:
            content = MediaPipelineTests.audio.read_bytes()
            self.graph.videos = self.graph.videos[:1]
            self.graph.reels = []
            self.graph.instagram = []
            self.graph.ads = []
            original = httpx.Client
            with (
                patch("app.meta_library_worker.analyze_file", side_effect=analyze_file),
                patch("app.meta_library_worker.download", side_effect=download),
                patch(
                    "app.meta_media.socket.getaddrinfo",
                    return_value=[(0, 0, 0, "", ("8.8.8.8", 443))],
                ),
                patch(
                    "app.meta_media.httpx.Client",
                    side_effect=lambda **kw: original(
                        transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, content=content)
                        ),
                        **kw,
                    ),
                ),
            ):
                self.drain()
            identity = str(self.item("100")["id"])
            result = self.api.get("/api/meta/library/" + identity)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["analysis_state"], "completed", result.text)
            self.assertIn(
                "VIDEO TEST",
                " ".join(
                    r["text"] for r in result.json()["analysis"]["on_screen_text"]
                ).upper(),
            )
            with patch(
                "app.meta_library_routes.recommend_videos",
                return_value={"model": "test", "response": "Idea and script"},
            ) as recommend:
                response = self.api.post(
                    "/api/meta/recommendations", json={"video_ids": [identity]}
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                recommend.call_args.args[0]["videos"][0]["metadata"]["audio"]["codec"],
                "aac",
            )
            self.assertEqual(
                recommend.call_args.args[0]["performance_snapshots"][0]["snapshot"][
                    "performance_metrics"
                ]["view_count"],
                100,
            )
        finally:
            MediaPipelineTests.tearDownClass()


@unittest.skipUnless(
    os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL"
)
class MetaLibraryMigrationTests(unittest.TestCase):
    def test_populated_legacy_schema_is_preserved(self):
        schema = "meta_preserve_" + uuid4().hex
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")
            try:
                url = make_conninfo(
                    os.environ["TEST_DATABASE_URL"], options=f"-csearch_path={schema}"
                )
                with (
                    patch.dict(os.environ, {"DATABASE_URL": url}),
                    psycopg.connect(url, autocommit=True) as db,
                ):
                    migrations = sorted(
                        (Path(__file__).resolve().parents[1] / "migrations").glob(
                            "*.sql"
                        )
                    )
                    for path in migrations[:4]:
                        db.execute(path.read_text())
                    identity = UUID(save_analysis(ANALYSIS))
                    db.execute(
                        "INSERT INTO video_performance(video_id,source,view_count,fetched_at) VALUES (%s,'tiktok',0,'2026-01-01Z')",
                        (identity,),
                    )
                    before = get_analysis(identity)
                    performance = db.execute(
                        "SELECT * FROM video_performance"
                    ).fetchall()
                    db.execute(migrations[4].read_text())
                    self.assertEqual(get_analysis(identity), before)
                    self.assertEqual(
                        db.execute("SELECT * FROM video_performance").fetchall(),
                        performance,
                    )
                    self.assertEqual(
                        db.execute("SELECT analysis_version FROM videos").fetchone(),
                        (1,),
                    )
            finally:
                admin.execute(f"DROP SCHEMA {schema} CASCADE")
