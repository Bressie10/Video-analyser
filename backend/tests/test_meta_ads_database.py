"""Real migration and ad Insights -> API -> repository -> API round trips."""

from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from auth_fixtures import USER_ID
from app import meta
from app.video_repository import get_analysis, save_analysis, save_performance
from test_meta_ads_api import CONFIG, ROW, attach, authenticated_api, graph_transport
from test_recommendations_api import ANALYSIS


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class MetaAdsDatabaseTests(unittest.TestCase):
    def setUp(self):
        from app.main import app
        from app.meta_auth_dependencies import require_meta_session
        from app.auth import require_authenticated_user, AuthenticatedUser
        from auth_fixtures import USER_ID
        app.dependency_overrides[require_authenticated_user] = lambda: AuthenticatedUser(USER_ID, 'fixture@example.com')
        self.addCleanup(lambda: app.dependency_overrides.pop(require_authenticated_user, None))
        app.dependency_overrides[require_meta_session] = lambda: None
        self.addCleanup(lambda: app.dependency_overrides.pop(require_meta_session, None))

    def test_migration_attachment_refresh_nulls_and_legacy_isolation(self):
        schema = 'meta_ads_test_' + uuid4().hex
        migrations = Path(__file__).resolve().parents[1] / 'migrations'
        with psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True) as admin:
            admin.execute(f'CREATE SCHEMA {schema}')
            try:
                url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={schema}')
                with psycopg.connect(url, autocommit=True) as db, patch.dict(os.environ, {**CONFIG, 'DATABASE_URL': url}):
                    for migration in sorted(migrations.glob('00[123]_*.sql')):
                        db.execute(migration.read_text())
                    legacy = db.execute("INSERT INTO videos (duration_seconds, container, file_size_bytes) VALUES (1,'mp4',1) RETURNING id").fetchone()[0]
                    db.execute("INSERT INTO video_performance (video_id, source, view_count, fetched_at) VALUES (%s,'tiktok',0,'2026-01-01 UTC')", (legacy,))
                    before = db.execute('SELECT * FROM video_performance').fetchone()
                    db.execute((migrations / '004_meta_ads_metrics.sql').read_text())
                    after = db.execute('SELECT * FROM video_performance').fetchone()
                    self.assertEqual(after[:-1], before)
                    self.assertIsNone(after[-1])

                    for migration in sorted(migrations.glob('*.sql')):
                        if int(migration.name[:3]) >= 5: db.execute(migration.read_text())
                    # Include ordered children so changing performance cannot corrupt video analysis.
                    analysis = deepcopy(ANALYSIS)
                    analysis['scenes'] = [{'scene_number': 1, 'start_seconds': 0, 'end_seconds': 1,
                                           'duration_seconds': 1, 'cut_timestamp_seconds': None}]
                    analysis['motion_events'] = [{'start_seconds': 0, 'end_seconds': 1, 'type': 'camera_pan', 'confidence': 0.9}]
                    target = UUID(save_analysis(analysis, owner_user_id=USER_ID))
                    unrelated = UUID(save_analysis(ANALYSIS, owner_user_id=USER_ID))
                    before_analysis = get_analysis(target)
                    api = authenticated_api()
                    with graph_transport():
                        response = attach(api, target)
                    self.assertEqual(response.status_code, 200, response.text)
                    snapshot = {k: response.json()[k] for k in ('performance_source', 'performance_metrics')}
                    self.assertEqual(get_analysis(target), {**before_analysis, **snapshot})
                    self.assertEqual(api.get(f'/api/videos/{target}/analysis').json(), get_analysis(target))
                    stored = db.execute('SELECT source, view_count, meta_ads, fetched_at FROM video_performance WHERE video_id=%s', (target,)).fetchone()
                    self.assertEqual(stored[:3], ('meta_ads', 300, snapshot['performance_metrics']['meta_ads']))
                    self.assertNotIn('performance_metrics', get_analysis(unrelated))
                    self.assertNotIn('meta_ads', get_analysis(legacy)['performance_metrics'])
                    # The save_analysis entry point must also retain the full extended snapshot.
                    initial = UUID(save_analysis({**ANALYSIS, **snapshot}))
                    self.assertEqual(get_analysis(initial)['performance_metrics'], snapshot['performance_metrics'])

                    row = {key: ROW[key] for key in ('ad_id', 'account_id', 'date_start', 'date_stop')}
                    with graph_transport(row={**row, 'spend': '0.00'}):
                        response = attach(api, target)
                    self.assertEqual(response.status_code, 200, response.text)
                    refreshed = get_analysis(target)['performance_metrics']
                    self.assertIsNone(refreshed['view_count'])
                    self.assertEqual(refreshed['meta_ads']['spend'], '0.00')
                    self.assertIsNone(refreshed['meta_ads']['impressions'])
                    self.assertIsNone(refreshed['meta_ads']['actions'])
                    timestamp = db.execute('SELECT fetched_at FROM video_performance WHERE video_id=%s', (target,)).fetchone()[0]
                    self.assertGreater(timestamp, stored[3])
                    for payload, status in (({'data': []}, 422), ({'data': [{**ROW, 'ad_id': 'wrong'}]}, 502)):
                        with graph_transport(payload=payload):
                            self.assertEqual(attach(api, target).status_code, status)
                        self.assertEqual(get_analysis(target)['performance_metrics'], refreshed)
                    with graph_transport() as requests:
                        self.assertEqual(attach(api, legacy).status_code, 404)  # unclaimed legacy upload is hidden
                        self.assertEqual(attach(api, uuid4()).status_code, 404)
                        self.assertEqual(requests, [])
                    self.assertFalse(save_performance(uuid4(), snapshot))
                    for detail in ({'conversions': [{'action_type': 'purchase', '1d_view': '0'}]},
                                   {'video_play_actions': [{'action_type': 'video_view', 'value': '0'}]}):
                        with graph_transport(row={**row, **detail}):
                            self.assertEqual(attach(api, target).status_code, 200)
                    # Database guards still reject empty or incorrectly sourced snapshots.
                    for details in ({}, {'date_start': '2026-09-01'}, {'actions': []}):
                        with self.assertRaises(psycopg.IntegrityError):
                            db.execute('UPDATE video_performance SET meta_ads=%s WHERE video_id=%s', (Jsonb(details), target))
                    with self.assertRaises(psycopg.IntegrityError):
                        db.execute('UPDATE video_performance SET meta_ads=%s WHERE video_id=%s', (Jsonb(snapshot['performance_metrics']['meta_ads']), legacy))
                    db.execute('DELETE FROM videos WHERE id=%s', (target,))
                    self.assertEqual(db.execute('SELECT count(*) FROM video_performance WHERE video_id=%s', (target,)).fetchone()[0], 0)
            finally:
                meta._sessions.clear()
                admin.execute(f'DROP SCHEMA {schema} CASCADE')
