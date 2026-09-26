"""Disposable real FastAPI/worker/PostgreSQL server for browser integration tests.

Only external Meta, media delivery and OpenAI boundaries are controlled fixtures.
Routes, validation, sessions, queues, processing and persistence are production code.
Run only through frontend/tests/integration.test.mjs with TEST_DATABASE_URL.
"""

import json
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main():
    admin_url = os.environ["TEST_DATABASE_URL"]
    directory = Path(os.environ["META_E2E_DIRECTORY"])
    dbname = "meta_browser_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    params = conninfo_to_dict(admin_url)
    params["dbname"] = dbname
    database_url = make_conninfo(**params)
    # Set test-only configuration before importing the application or loading .env.
    os.environ.update({
        "TEST_DATABASE_URL": database_url,
        "DATABASE_URL": database_url,
        "OPENAI_API_KEY": "fixture-only-key",
        "HF_HUB_OFFLINE": "1",
        "META_WORKER_ENABLED": "false",
    })
    from test_meta_library import MetaLibraryDatabaseTests
    from test_meta_media_pipeline import MediaPipelineTests
    from app import meta
    from app import meta_library_repository as repo
    from app.analysis_pipeline import analyze_file
    from app.main import app

    fixture = MetaLibraryDatabaseTests()
    setup_done = media_done = False
    analysis_calls = []
    provider_inputs = []
    try:
        fixture.setUp()
        setup_done = True
        MediaPipelineTests.setUpClass()
        media_done = True
        fixture.graph.test_connection = lambda: {"connected": True}

        def actual_analysis(*args, **kwargs):
            result = analyze_file(*args, **kwargs)
            analysis_calls.append({"duration": result["metadata"]["duration_seconds"], "scene_count": len(result["scenes"])})
            return result

        fixture.analysis.side_effect = actual_analysis
        fixture.download.side_effect = lambda url, destination: Path(destination).write_bytes(MediaPipelineTests.audio.read_bytes())

        class FixtureOpenAI:
            def __init__(self, **kwargs):
                if kwargs.get("api_key") != "fixture-only-key":
                    raise AssertionError("Unexpected credential source")
                self.responses = self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def create(self, **kwargs):
                evidence = json.loads(kwargs["input"].split("\n", 1)[1])
                provider_inputs.append(evidence)
                return SimpleNamespace(output_text="New video idea\nShow how your business solves a real customer problem.\nScript\nOpen with the question. Demonstrate the process. Invite viewers to visit.")

        patch("app.recommendations.OpenAI", FixtureOpenAI).start()
        os.environ["META_WORKER_ENABLED"] = "true"
        # The fixture session uses the real encrypted persistent connection and hashed session.
        session_file = directory / "session.json"
        session_file.write_text(json.dumps({"name": meta.SESSION_COOKIE, "value": fixture.session}))
        session_file.chmod(0o600)
        class TestServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                # Shut workers down gracefully without re-raising SIGTERM before
                # the evidence report and disposable database cleanup can run.
                previous = signal.signal(signal.SIGTERM, self.handle_exit)
                try:
                    yield
                finally:
                    signal.signal(signal.SIGTERM, previous)

        TestServer(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ["META_E2E_PORT"]), log_level="warning", access_log=False)).run()
        with repo.database() as db:
            report = {
                "analysis_calls": analysis_calls,
                "provider_inputs": provider_inputs,
                "stored_videos": db.execute("SELECT count(*) AS n FROM videos").fetchone()["n"],
                "stored_items": db.execute("SELECT count(*) AS n FROM meta_library_items").fetchone()["n"],
            }
        (directory / "report.json").write_text(json.dumps(report, default=str))
    finally:
        if setup_done:
            fixture.tearDown()
        if media_done:
            MediaPipelineTests.tearDownClass()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))
        admin.close()
        (directory / "session.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
