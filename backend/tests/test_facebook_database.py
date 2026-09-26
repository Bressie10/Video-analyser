"""TEST_DATABASE_URL enables an isolated-schema Facebook API/repository round trip."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from app import meta
from app.video_repository import PerformanceSourceConflict, get_analysis, save_analysis, save_performance
from test_facebook_api import CONFIG, SNAPSHOT, attach, authenticated_api, graph_transport, insights
from test_recommendations_api import ANALYSIS


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL")
class FacebookDatabaseTests(unittest.TestCase):
    def test_reel_roundtrip(self):
        self.roundtrip("reels")

    def test_video_roundtrip(self):
        self.roundtrip("videos")

    def roundtrip(self, kind):
        schema = "facebook_test_" + uuid4().hex
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")
            try:
                url = make_conninfo(os.environ["TEST_DATABASE_URL"], options=f"-csearch_path={schema}")
                with psycopg.connect(url, autocommit=True) as db:
                    for migration in sorted(migrations.glob("*.sql")):
                        db.execute(migration.read_text())
                    with patch.dict(os.environ, {**CONFIG, "DATABASE_URL": url}):
                        target = UUID(save_analysis(ANALYSIS))
                        unrelated = UUID(save_analysis(ANALYSIS))
                        tiktok = UUID(save_analysis({
                            **ANALYSIS, **SNAPSHOT, "performance_source": "tiktok",
                        }))
                        before = get_analysis(target)
                        api = authenticated_api()
                        with graph_transport(kind=kind) as requests:
                            response = attach(api, target, kind=kind)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(len(requests), 3)
                        self.assertEqual(response.json(), {"video_id": str(target), **SNAPSHOT})
                        expected = {**before, **SNAPSHOT}
                        self.assertEqual(get_analysis(target), expected)
                        self.assertEqual(api.get(f"/api/videos/{target}/analysis").json(), expected)
                        self.assertNotIn("performance_metrics", get_analysis(unrelated))
                        self.assertEqual(get_analysis(tiktok)["performance_source"], "tiktok")

                        first_time = db.execute(
                            "SELECT fetched_at FROM video_performance WHERE video_id = %s", (target,),
                        ).fetchone()[0]
                        with graph_transport(metrics=insights({
                            "fb_reels_total_plays" if kind == "reels" else "total_video_views": 0,
                        })):
                            response = attach(api, target, kind=kind)
                        self.assertEqual(response.status_code, 200)
                        refreshed = {
                            "view_count": 0, "like_count": None, "comment_count": None, "share_count": None,
                        }
                        self.assertEqual(get_analysis(target)["performance_metrics"], refreshed)
                        rows = db.execute(
                            "SELECT source, view_count, like_count, comment_count, share_count, fetched_at "
                            "FROM video_performance WHERE video_id = %s", (target,),
                        ).fetchall()
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(rows[0][:5], ("facebook", 0, None, None, None))
                        self.assertGreater(rows[0][5], first_time)
                        refreshed_time = rows[0][5]

                        with graph_transport(metrics={"data": []}):
                            self.assertEqual(attach(api, target, kind=kind).status_code, 422)
                        self.assertEqual(get_analysis(target)["performance_metrics"], refreshed)
                        self.assertEqual(db.execute(
                            "SELECT fetched_at FROM video_performance WHERE video_id = %s", (target,),
                        ).fetchone()[0], refreshed_time)
                        with graph_transport(kind=kind) as requests:
                            self.assertEqual(attach(api, tiktok).status_code, 409)
                            self.assertEqual(attach(api, uuid4()).status_code, 404)
                            self.assertEqual(requests, [])
                        self.assertFalse(save_performance(uuid4(), SNAPSHOT))
                        with self.assertRaises(PerformanceSourceConflict):
                            save_performance(tiktok, SNAPSHOT)
                        self.assertEqual(get_analysis(tiktok)["performance_metrics"], SNAPSHOT["performance_metrics"])
                        for key in ("metadata", "audio", "scenes", "on_screen_text", "motion_events"):
                            self.assertEqual(get_analysis(target)[key], before[key])
                        self.assertEqual(db.execute("SELECT count(*) FROM videos").fetchone()[0], 3)
                        self.assertEqual(db.execute("SELECT count(*) FROM video_performance").fetchone()[0], 2)
            finally:
                meta._sessions.clear()
                admin.execute(f"DROP SCHEMA {schema} CASCADE")
