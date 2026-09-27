"""Wave 2 browser fixture: real HTTP, sessions, migrations and persistence; offline model."""
import json
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ.update(META_WORKER_ENABLED='false', COMPANY_PROFILE_WORKER_ENABLED='false')
from test_idea_integration import IdeaIntegrationTests
from app import meta
from app.main import app
import uvicorn


def main():
    fixture = IdeaIntegrationTests('test_real_adapter_shared_creative_and_profile_revisions')
    directory = Path(os.environ['COMPANY_E2E_DIRECTORY'])
    try:
        fixture.setUp()
        f = fixture.f
        from auth_fixtures import LocalAuth, USER_ID
        from app.auth import get_token_verifier
        from app.auth_repository import ensure_profile
        auth = LocalAuth()
        jwks = auth.serve_jwks()
        jwks.start()
        fixture.addCleanup(jwks.stop)
        app.dependency_overrides[get_token_verifier] = lambda: auth.verifier
        fixture.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        ensure_profile(f.db, USER_ID)
        f.db.execute('UPDATE meta_connections SET owner_user_id=%s WHERE id=%s', (USER_ID, f.connection))
        # 25 eligible A items, with distinct library/video IDs; unrelated B rows exist too.
        f.db.execute("UPDATE meta_library_items SET published_at='2026-01-01T00:00:00Z'")
        for index in range(22):
            identity = f.item(f.fb, f'wave2-{index}', 'video', 'facebook')
            f.db.execute("""UPDATE meta_library_items SET video_id=%s,analysis_state='completed',
                analysis_version=1,published_at=%s WHERE id=%s""", (f.video, f'2026-02-{index+1:02}T00:00:00Z', identity))
            f.db.execute('DELETE FROM meta_library_performance WHERE item_id=%s', (identity,))
        pending = f.item(f.fb, 'pending-no-video', 'video', 'facebook')
        # Unassigned accounts let the release flow start with a name-only company.
        fb = f.account('facebook', 'release-fb')
        ig = f.account('instagram', 'release-ig')
        f.db.execute("UPDATE meta_accounts SET label='Release Facebook' WHERE id=%s", (fb,))
        f.db.execute("UPDATE meta_accounts SET label='Release Instagram' WHERE id=%s", (ig,))
        for index in range(25):
            identity = f.item(ig if index == 0 else fb, f'release-{index}',
                              'reel' if index == 0 else 'video', 'instagram' if index == 0 else 'facebook')
            f.db.execute("""UPDATE meta_library_items SET video_id=%s,analysis_state='completed',
                analysis_version=1,published_at=%s WHERE id=%s""", (f.video, f'2026-03-{index+1:02}T00:00:00Z', identity))
            f.db.execute('DELETE FROM meta_library_performance WHERE item_id=%s', (identity,))
        f.item(fb, 'release-pending', 'video', 'facebook')
        (directory / 'session.json').write_text(json.dumps({'name': meta.SESSION_COOKIE, 'value': 'integration-session', 'jwt': auth.token()}))
        (directory / 'session.json').chmod(0o600)
        class Server(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                previous = signal.signal(signal.SIGTERM, self.handle_exit)
                try:
                    yield
                finally:
                    signal.signal(signal.SIGTERM, previous)
        with patch('app.meta_library_repository.connection_client') as client, \
                patch('app.company_profile_worker.OpenAIProfileGenerator', return_value=fixture.fixture.generator), \
                patch.dict(os.environ, {'COMPANY_PROFILE_WORKER_ENABLED': 'true'}):
            client.return_value.test_connection.return_value = {'connected': True}
            Server(uvicorn.Config(app, host='127.0.0.1', port=int(os.environ.get("FRONTEND_E2E_PORT", "8063")), log_level='warning', access_log=False)).run()
        (directory / 'report.json').write_text(json.dumps({
            'ideas': f.db.execute('SELECT title,script,status,feedback FROM ideas').fetchall(),
            'model_calls': fixture.model.call_count,
        }, default=str))
    finally:
        fixture.doCleanups()
        (directory / 'session.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
