"""Creative Analysis detail and media authorization against disposable PostgreSQL."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser, require_authenticated_user
from app.main import app
import test_performance_observations_database as fixture
import test_stage8_1_intelligence as intelligence_fixture


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CreativeAnalysisDatabaseTests(unittest.TestCase):
    setUp = fixture.ObservationDatabaseTests.setUp
    cleanup_schema = fixture.ObservationDatabaseTests.cleanup_schema
    seed = intelligence_fixture.IntelligenceDatabaseTests.seed

    def asset_ref(self):
        return self.db.execute("SELECT video_item_id FROM meta_ad_assets LIMIT 1").fetchone()['video_item_id']

    def test_detail_requires_current_company_access_and_keeps_stored_evidence(self):
        self.seed(content=True)
        asset = self.asset_ref()
        app.dependency_overrides[require_authenticated_user] = lambda: AuthenticatedUser(self.user.user_id)
        self.addCleanup(lambda: app.dependency_overrides.pop(require_authenticated_user, None))
        with TestClient(app) as client:
            path = f'/api/companies/{self.company}/creatives/{asset}/analysis'
            allowed = client.get(path)
            self.assertEqual(allowed.status_code, 200, allowed.text)
            self.assertEqual(allowed.json()['creative_ref'], str(asset))
            self.assertTrue(allowed.json()['scenes'])
            self.assertEqual(client.get(f'/api/companies/{self.other_company}/creatives/{asset}/analysis').status_code, 404)
            self.db.execute('DELETE FROM company_memberships WHERE company_id=%s AND user_id=%s',
                            (self.company, self.user.user_id))
            self.assertEqual(client.get(path).status_code, 403)

    def test_media_grant_and_each_range_reauthorize_current_company(self):
        self.seed(content=True)
        asset = self.asset_ref()
        app.dependency_overrides[require_authenticated_user] = lambda: AuthenticatedUser(self.user.user_id)
        self.addCleanup(lambda: app.dependency_overrides.pop(require_authenticated_user, None))
        root = f'/api/companies/{self.company}/creatives/{asset}'
        verifier = type('Verifier', (), {'verify': lambda _, token: AuthenticatedUser(self.user.user_id)})()
        with patch('app.creative_analysis_routes.bearer_token', return_value='fixture-jwt'), \
             patch('app.creative_analysis_routes.get_token_verifier', return_value=verifier), \
             patch('app.creative_analysis_routes.library.connection_client', return_value=object()), \
             patch('app.creative_analysis_routes.media_url', return_value='https://video.xx.fbcdn.net/fixture') as resolve, \
             patch('app.creative_analysis_routes._open_media') as upstream, TestClient(app) as client:
            class Stream:
                status_code = 206
                def iter_raw(self, chunk_size): yield b'0123456789'
                def close(self): pass
            class Connection:
                def close(self): pass
            upstream.return_value = (Connection(), Stream(), {
                'Content-Type': 'video/mp4', 'Content-Length': '10',
                'Content-Range': 'bytes 0-9/100', 'Accept-Ranges': 'bytes'})
            grant = client.post(f'{root}/media-access')
            self.assertEqual(grant.status_code, 200, grant.text)
            cookie = grant.headers['set-cookie']
            self.assertIn('httponly', cookie.lower())
            self.assertIn('samesite=strict', cookie.lower())
            self.assertIn(f'/api/companies/{self.company}/creatives/{asset}/media', cookie)
            media_headers = {'Range': 'bytes=0-9', 'Cookie': cookie.split(';', 1)[0]}
            self.assertEqual(client.get(f'{root}/media', headers=media_headers).status_code, 206)
            self.assertEqual(client.get(f'{root}/media', headers=media_headers).status_code, 206)
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(upstream.call_count, 2)
            self.db.execute('DELETE FROM company_memberships WHERE company_id=%s AND user_id=%s',
                            (self.company, self.user.user_id))
            self.assertEqual(client.get(f'{root}/media', headers=media_headers).status_code, 403)
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(upstream.call_count, 2)
