"""Real company HTTP/session/PostgreSQL fixture; Meta status and JWKS transport are stubbed."""
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

from test_company_api import CompanyAPITests
from app import meta
from app.main import app
import uvicorn


def main():
    fixture = CompanyAPITests('test_name_only_lifecycle')
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
        for account, label in [(f.fb, 'Facebook Page'), (f.ig, 'Instagram Business'), (f.ads, 'Ads Business')]:
            f.db.execute('UPDATE meta_accounts SET label=%s WHERE id=%s', (label, account))
        for ad, label in [(f.ad_a, 'Summer ad'), (f.ad_b, 'Winter ad'), (f.unassigned, 'Unused ad')]:
            f.db.execute('UPDATE meta_library_items SET label=%s WHERE id=%s', (label, ad))
        # Foreign company/account/ad and raw provider IDs stay in the fixture to test redaction.
        (directory / 'session.json').write_text(json.dumps({'name': meta.SESSION_COOKIE, 'value': 'company-api-session', 'jwt': auth.token()}))
        (directory / 'session.json').chmod(0o600)
        class Server(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                previous = signal.signal(signal.SIGTERM, self.handle_exit)
                try:
                    yield
                finally:
                    signal.signal(signal.SIGTERM, previous)
        with patch('app.meta_library_repository.connection_client') as client:
            client.return_value.test_connection.return_value = {'connected': True}
            Server(uvicorn.Config(app, host='127.0.0.1', port=int(os.environ.get("FRONTEND_E2E_PORT", "8062")), log_level='warning', access_log=False)).run()
        rows = f.db.execute('SELECT name,archived_at FROM companies WHERE connection_id=%s ORDER BY name', (f.connection,)).fetchall()
        (directory / 'report.json').write_text(json.dumps(rows, default=str))
    finally:
        fixture.doCleanups()
        (directory / 'session.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
