"""Test-only V7 browser server with real API/database and mocked external providers."""
import json
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ.update(META_WORKER_ENABLED='false', COMPANY_PROFILE_WORKER_ENABLED='false')
from app.main import app
from app.auth import get_token_verifier
from app.video_repository import save_analysis
from test_meta_v6_auth import MetaV6Tests
from test_persistent_ideas import RESULT
from test_recommendations_api import ANALYSIS
from auth_fixtures import USER_ID, OTHER_USER_ID


def main():
    fixture = MetaV6Tests('test_auth_required_and_json_initiation')
    directory = Path(os.environ['V7_E2E_DIRECTORY'])
    try:
        fixture.setUp()
        app.dependency_overrides[get_token_verifier] = lambda: fixture.auth.verifier
        fixture.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        (directory / 'session.json').write_text(json.dumps({
            'user_a': fixture.auth.token(sub=str(USER_ID)),
            'user_b': fixture.auth.token(sub=str(OTHER_USER_ID)),
        }))
        state = {}

        def connection_id():
            return fixture.db.execute('SELECT id FROM meta_connections WHERE owner_user_id=%s',
                                      (USER_ID,)).fetchone()['id']

        def seed_content():
            connection = connection_id()
            account = fixture.db.execute('''INSERT INTO meta_accounts(connection_id,platform,external_id,label)
                VALUES (%s,'instagram',%s,'V7 Instagram') RETURNING id''',
                (connection, str(uuid4()))).fetchone()['id']
            item = fixture.db.execute('''INSERT INTO meta_library_items
                (connection_id,account_id,platform,external_id,content_type,label,published_at,analysis_state)
                VALUES (%s,%s,'instagram',%s,'reel','First reel',now(),'discovered') RETURNING id''',
                (connection, account, str(uuid4()))).fetchone()['id']
            state.update(account=account, item=item)
            return {'account_id': str(account), 'item_id': str(item)}

        def finish_analysis():
            item = state['item']
            queued = fixture.db.execute("SELECT 1 FROM meta_jobs WHERE item_id=%s AND kind='analysis'", (item,)).fetchone()
            if not queued:
                raise RuntimeError('Analysis was not requested through the production endpoint.')
            video = save_analysis(ANALYSIS, connection=fixture.db)
            fixture.db.execute('UPDATE videos SET meta_connection_id=%s,analysis_version=1 WHERE id=%s',
                               (connection_id(), video))
            fixture.db.execute("""UPDATE meta_library_items SET video_id=%s,analysis_version=1,
                analysis_state='completed' WHERE id=%s""", (video, item))
            return {'completed': True}

        def disconnect():
            fixture.db.execute("UPDATE meta_connections SET status='disconnected' WHERE id=%s", (connection_id(),))
            return {'disconnected': True}

        app.add_api_route('/__v7_fixture/content', seed_content, methods=['POST'], include_in_schema=False)
        app.add_api_route('/__v7_fixture/complete-analysis', finish_analysis, methods=['POST'], include_in_schema=False)
        app.add_api_route('/__v7_fixture/disconnect', disconnect, methods=['POST'], include_in_schema=False)

        class Server(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                previous = signal.signal(signal.SIGTERM, self.handle_exit)
                try:
                    yield
                finally:
                    signal.signal(signal.SIGTERM, previous)

        with patch('app.idea_service.generate_idea', return_value=RESULT):
            Server(uvicorn.Config(app, host='127.0.0.1', port=8165,
                                  log_level='warning', access_log=False)).run()
    finally:
        fixture.doCleanups()
        (directory / 'session.json').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
