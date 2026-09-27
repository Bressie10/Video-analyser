"""V6 signed application JWT -> OAuth -> real PostgreSQL, mocked provider only."""
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app import meta, meta_library_repository as repo
from app.auth import get_token_verifier
from app.auth_repository import CompanyAccessDenied
from app.main import app
from auth_fixtures import LocalAuth, USER_ID, OTHER_USER_ID
from test_meta_api import CONFIG


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class MetaV6Tests(unittest.TestCase):
    def setUp(self):
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.schema = 'meta_v6_' + uuid4().hex
        self.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={self.schema}')
        self.db = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self.addCleanup(self.db.close)
        for path in sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql')):
            self.db.execute(path.read_text())
        env = patch.dict(os.environ, {**CONFIG, 'DATABASE_URL': self.url,
            'META_TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode()})
        env.start()
        self.addCleanup(env.stop)
        self.auth = LocalAuth()
        transport = self.auth.serve_jwks()
        transport.start()
        self.addCleanup(transport.stop)
        app.dependency_overrides[get_token_verifier] = lambda: self.auth.verifier
        self.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        self.api = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.api.close)
        self.addCleanup(meta._states.clear)
        self.token = meta.UserToken('provider-private-token', time.time()+3600)
        self.graph = unittest.mock.Mock()
        self.graph.test_connection.return_value = {'connected': True}
        self.graph.get.return_value = {'id': '123'}
        for target, kwargs in (
            ('app.meta.exchange_code', {'return_value': self.token}),
            ('app.meta.extend_token', {'return_value': self.token}),
            ('app.meta.MetaClient', {'return_value': self.graph}),
        ):
            mock = patch(target, **kwargs)
            setattr(self, target.rsplit('.', 1)[1], mock.start())
            self.addCleanup(mock.stop)

    def cleanup_schema(self):
        self.admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.admin.close()

    def headers(self, user=USER_ID):
        return {'Authorization': 'Bearer '+self.auth.token(sub=str(user))}

    def begin(self, user=USER_ID, mode='redirect'):
        result = self.api.get('/api/meta/connect', headers=self.headers(user),
                              params={'response_mode': mode}, follow_redirects=False)
        self.assertEqual(result.status_code, 200 if mode == 'json' else 302)
        url = result.json()['authorization_url'] if mode == 'json' else result.headers['location']
        self.assertNotIn(str(user), url)
        return parse_qs(urlsplit(url).query)['state'][0]

    def callback(self, state, **params):
        return self.api.get('/api/meta/callback', params={'state': state, 'code': 'code', **params})

    def connect(self, user=USER_ID):
        response = self.callback(self.begin(user))
        self.assertEqual(response.status_code, 200, response.text)
        return repo.session_connection(self.api.cookies.get(meta.SESSION_COOKIE))

    def test_auth_required_and_json_initiation(self):
        for path in ('/connect', '/test', '/library', '/discovery/pages'):
            self.assertEqual(self.api.get('/api/meta'+path).status_code, 401)
        self.assertEqual(self.api.get('/api/meta/connect', headers={'Authorization': 'Bearer bad'}).status_code, 401)
        self.assertEqual(self.callback(self.begin(mode='json')).status_code, 200)

    def test_callback_binds_initiator_not_query_or_callback_header(self):
        state = self.begin()
        response = self.api.get('/api/meta/callback', params={'state': state, 'code': 'code',
                                'user_id': str(OTHER_USER_ID)}, headers=self.headers(OTHER_USER_ID))
        self.assertEqual(response.status_code, 200)
        connection = repo.session_connection(self.api.cookies.get(meta.SESSION_COOKIE))
        self.assertEqual(connection['owner_user_id'], USER_ID)
        self.assertNotIn(self.token.access_token, response.text + str(response.headers))
        self.assertNotIn(self.token.access_token, connection['token_ciphertext'])
        self.assertEqual(repo.cipher().decrypt(connection['token_ciphertext'].encode()).decode(), self.token.access_token)
        self.assertEqual(len(repo.list_meta_connections_for_user(self.db, USER_ID)), 1)
        self.assertEqual(repo.list_meta_connections_for_user(self.db, OTHER_USER_ID), [])

    def test_missing_malformed_expired_replay_and_cookie_mismatch(self):
        state = self.begin()
        for params in ({}, {'state': ''}, {'state': '☃'}, {'state': 'unknown'}):
            self.assertEqual(self.api.get('/api/meta/callback', params=params).status_code, 400)
        self.exchange_code.assert_not_called()
        state = self.begin()
        self.api.cookies.clear()
        self.assertEqual(self.callback(state).status_code, 400)
        self.begin(OTHER_USER_ID)
        self.assertEqual(self.callback(state).status_code, 400)
        self.exchange_code.assert_not_called()
        state = self.begin()
        with patch('app.meta.time.time', return_value=time.time()+601):
            self.assertEqual(self.callback(state).status_code, 400)
        self.exchange_code.assert_not_called()
        state = self.begin()
        self.assertEqual(self.callback(state).status_code, 200)
        self.api.cookies.set(meta.STATE_COOKIE, state, path='/api/meta/callback')
        self.assertEqual(self.callback(state).status_code, 400)
        self.assertEqual(self.exchange_code.call_count, 1)

    def test_provider_permission_and_persistence_failure_consume_state(self):
        for error, expected in ((meta.MetaError('safe'), 502), (meta.MetaPermissionError('safe'), 403)):
            state = self.begin()
            self.graph.verify_permissions.side_effect = error
            self.assertEqual(self.callback(state).status_code, expected)
            self.assertNotIn(state, meta._states)
        self.graph.verify_permissions.side_effect = None
        state = self.begin()
        self.assertEqual(self.callback(state, error='denied').status_code, 400)
        self.assertNotIn(state, meta._states)
        state = self.begin()
        with patch('app.meta_library_repository.enqueue_sync', side_effect=ValueError('failed')):
            self.assertEqual(self.callback(state).status_code, 503)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM meta_connections').fetchone()['n'], 0)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM user_profiles').fetchone()['n'], 0)

    def test_reconnect_same_owner_cross_user_conflict_and_cookie_theft(self):
        connection = self.connect()
        old_cookie = self.api.cookies.get(meta.SESSION_COOKIE)
        self.assertEqual(self.connect()['id'], connection['id'])
        with self.assertRaises(meta.MetaNotConnected):
            repo.session_connection(old_cookie)
        for path, method in (('/test', 'get'), ('/library', 'get'), ('/discovery/pages', 'get'),
                             ('/sync', 'post'), ('/disconnect', 'post'),
                             ('/ads/123/metrics', 'post'), ('/instagram/reels/123/metrics', 'post'),
                             ('/facebook/videos/123/metrics', 'post')):
            self.assertEqual(getattr(self.api, method)('/api/meta'+path, headers=self.headers(OTHER_USER_ID)).status_code, 403)
        self.assertEqual(self.api.get('/api/meta/test', headers=self.headers()).json(), {'connected': True})
        before = self.db.execute('SELECT * FROM meta_connections').fetchone()
        self.assertEqual(self.callback(self.begin(OTHER_USER_ID)).status_code, 409)
        self.assertEqual(self.db.execute('SELECT * FROM meta_connections').fetchone(), before)
        repo.require_meta_connection_owner(self.db, USER_ID, connection['id'])
        for user in (OTHER_USER_ID, uuid4()):
            with self.assertRaises(CompanyAccessDenied):
                repo.list_meta_accounts_for_user(self.db, user, connection['id'])
        self.assertEqual(repo.list_meta_accounts_for_user(self.db, USER_ID, connection['id']), [])

    def test_legacy_survives_unclaimed_and_unusable(self):
        connection = self.connect()
        self.db.execute('UPDATE meta_connections SET owner_user_id=NULL')
        before = self.db.execute('SELECT * FROM meta_connections').fetchone()
        self.assertEqual(self.api.get('/api/meta/test', headers=self.headers()).status_code, 403)
        self.assertEqual(self.callback(self.begin()).status_code, 409)
        self.assertEqual(self.db.execute('SELECT * FROM meta_connections').fetchone(), before)
        self.assertEqual(repo.list_meta_connections_for_user(self.db, USER_ID), [])
        with self.assertRaises(CompanyAccessDenied):
            repo.require_meta_connection_owner(self.db, USER_ID, connection['id'])

    def test_invalid_stale_cookie_and_multiple_connections(self):
        self.assertEqual(self.api.get('/api/meta/test', headers=self.headers()).json(), {'connected': False})
        self.api.cookies.set(meta.SESSION_COOKIE, 'invalid', domain='testserver.local', path='/api')
        self.assertEqual(self.api.get('/api/meta/test', headers=self.headers()).json(), {'connected': False})
        self.connect()
        self.db.execute("UPDATE meta_sessions SET expires_at=now()-interval '1 second'")
        self.assertEqual(self.api.get('/api/meta/test', headers=self.headers()).json(), {'connected': False})
        repo.connect_identity('456', self.token, owner_user_id=USER_ID)
        self.assertEqual(len(repo.list_meta_connections_for_user(self.db, USER_ID)), 2)

    def test_concurrent_distinct_owners_have_one_winner(self):
        barrier = Barrier(2)
        def connect(user):
            barrier.wait(timeout=5)
            try:
                repo.connect_identity('123', self.token, owner_user_id=user)
                return user
            except repo.MetaOwnershipConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = list(pool.map(connect, (USER_ID, OTHER_USER_ID)))
        self.assertEqual(sum(winner is not None for winner in winners), 1)
        row = self.db.execute('SELECT * FROM meta_connections').fetchone()
        self.assertIn(row['owner_user_id'], winners)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM meta_sessions').fetchone()['n'], 1)

    def test_concurrent_same_owner_and_state_consumption(self):
        barrier = Barrier(2)
        def connect(_):
            barrier.wait(timeout=5)
            return repo.connect_identity('123', self.token, owner_user_id=USER_ID)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(connect, range(2)))
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(self.db.execute('SELECT count(*) n FROM meta_connections').fetchone()['n'], 1)
        state = self.begin()
        def consume(_):
            try:
                return meta.consume_state(state, state)[1]
            except meta.MetaError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, range(2)))
        self.assertEqual(results.count(USER_ID), 1)

    def test_encryption_is_required_and_foreign_previous_session_survives(self):
        with patch.dict(os.environ, {'META_TOKEN_ENCRYPTION_KEY': ''}):
            self.assertEqual(self.api.get('/api/meta/connect', headers=self.headers()).status_code, 503)
        foreign, _ = repo.connect_identity('456', self.token, owner_user_id=OTHER_USER_ID)
        repo.connect_identity('123', self.token, foreign, owner_user_id=USER_ID)
        self.assertEqual(repo.session_connection(foreign)['owner_user_id'], OTHER_USER_ID)

    def test_failed_reconnect_preserves_token_session_and_owner(self):
        self.connect()
        before = self.db.execute('SELECT * FROM meta_connections').fetchone()
        session = self.api.cookies.get(meta.SESSION_COOKIE)
        with patch('app.meta_library_repository.enqueue_sync', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                repo.connect_identity('123', meta.UserToken('replacement', time.time()+7200),
                                      session, owner_user_id=USER_ID)
        self.assertEqual(self.db.execute('SELECT * FROM meta_connections').fetchone(), before)
        self.assertEqual(repo.session_connection(session)['owner_user_id'], USER_ID)
