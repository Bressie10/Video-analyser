"""Set TEST_DATABASE_URL to run against a disposable PostgreSQL database."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

from app.main import app
from app.performance import performance_snapshot
from app.video_repository import get_analysis, save_analysis
from test_recommendations_api import ANALYSIS


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL")
class PerformanceDatabaseTests(unittest.TestCase):
    def test_migration_repository_api_and_model(self):
        schema = "metrics_test_" + uuid4().hex
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")
            try:
                url = make_conninfo(os.environ["TEST_DATABASE_URL"], options=f"-csearch_path={schema}")
                with psycopg.connect(url, autocommit=True) as db:
                    for name in ("001_create_video_analysis.sql", "002_create_tiktok_video_performance.sql"):
                        db.execute((migrations / name).read_text())
                    old_id = db.execute(
                        "INSERT INTO videos (duration_seconds, container, file_size_bytes) "
                        "VALUES (1, 'mp4', 1) RETURNING id"
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO tiktok_video_performance "
                        "(video_id, view_count, like_count, fetched_at) VALUES (%s, 0, 2, '2026-01-01 UTC')",
                        (old_id,),
                    )
                    before = db.execute("SELECT * FROM tiktok_video_performance").fetchone()
                    db.execute((migrations / "003_platform_agnostic_performance.sql").read_text())
                    after = db.execute(
                        "SELECT video_id, view_count, like_count, comment_count, share_count, fetched_at, source "
                        "FROM video_performance"
                    ).fetchone()
                    self.assertEqual(after[:-1], before)
                    self.assertEqual(after[-1], "tiktok")
                    db.execute((Path(__file__).parent / "schema_roundtrip.sql").read_text())
                    with patch.dict(os.environ, {"DATABASE_URL": url, "OPENAI_API_KEY": "test-key"}):
                        for source in ("tiktok", "instagram", "facebook", "meta_ads"):
                            with self.subTest(source=source):
                                snapshot = performance_snapshot(source, {"view_count": 0, "like_count": 2})
                                video_id = save_analysis({**ANALYSIS, **snapshot})
                                stored = get_analysis(UUID(video_id))
                                for key, value in snapshot.items():
                                    self.assertEqual(stored[key], value)
                                api = TestClient(app)
                                self.assertEqual(api.get(f"/api/videos/{video_id}/analysis").json(), stored)
                                with patch("app.recommendations.OpenAI") as model:
                                    sdk = model.return_value.__enter__.return_value
                                    sdk.responses.create.return_value.output_text = "Idea"
                                    self.assertEqual(api.post(f"/api/videos/{video_id}/recommendations").status_code, 200)
                                    sent = json.loads(sdk.responses.create.call_args.kwargs["input"].split("\n", 1)[1])
                                    self.assertEqual(sent, stored)
                                db.execute("DELETE FROM videos WHERE id = %s", (video_id,))
                                self.assertEqual(db.execute(
                                    "SELECT count(*) FROM video_performance WHERE video_id = %s", (video_id,),
                                ).fetchone()[0], 0)
                        plain_id = save_analysis(ANALYSIS)
                        self.assertNotIn("performance_metrics", get_analysis(UUID(plain_id)))
                        self.assertNotIn("performance_source", get_analysis(UUID(plain_id)))
                    for assignment in ("source = 'unknown'", "view_count = -1", "source = NULL",
                                       "view_count = NULL, like_count = NULL"):
                        with self.assertRaises(psycopg.IntegrityError):
                            db.execute(f"UPDATE video_performance SET {assignment}")
            finally:
                admin.execute(f"DROP SCHEMA {schema} CASCADE")
