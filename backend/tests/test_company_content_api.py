"""Company browsing against real sessions and disposable PostgreSQL."""
import json
import os
import unittest
from uuid import uuid4

from app import company_ownership_repository as ownership
from app import meta_library_repository as library
import test_company_api as company_tests


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyContentAPITests(unittest.TestCase):
    setUp = company_tests.CompanyAPITests.setUp
    request = company_tests.CompanyAPITests.request

    def browse(self, company=None, status=200, **params):
        return self.request('GET', f'/api/companies/{company or self.f.a}/content', status, params=params)

    def ids(self, company=None, **params):
        return {r['library_item_id'] for r in self.browse(company, **params)['items']}

    def analyzed(self, item, published='2026-01-01T00:00:00Z'):
        video = self.f.db.execute('''INSERT INTO videos
            (duration_seconds,container,file_size_bytes,meta_connection_id,analysis_version,width,height)
            VALUES (5,'mp4',100,%s,%s,1920,1080) RETURNING id''',
            (self.f.connection, library.ANALYSIS_VERSION)).fetchone()['id']
        self.f.db.execute('''UPDATE meta_library_items SET video_id=%s,
            analysis_state='completed',analysis_version=%s,published_at=%s WHERE id=%s''',
            (video, library.ANALYSIS_VERSION, published, item))
        return video

    def test_organic_company_scope(self):
        self.f.link(self.f.a, self.f.fb)
        self.f.link(self.f.b, self.f.ig)
        self.assertEqual(self.ids(), {str(self.f.organic)})
        self.assertEqual(self.ids(self.f.b), {str(self.f.instagram)})

    def test_shared_ads_and_safe_creative_projection(self):
        self.f.link(self.f.a, self.f.ads)
        self.f.link(self.f.b, self.f.ads)
        self.assertEqual(self.ids(), set())
        self.assertEqual(self.ids(self.f.b), set())
        self.f.assign(self.f.a, self.f.ad_a)
        self.f.assign(self.f.b, self.f.ad_b)
        self.f.db.execute("UPDATE meta_library_items SET label='Sibling campaign private', analysis_error='token-secret' WHERE id=%s", (self.f.creative,))
        self.f.db.execute("UPDATE meta_library_items SET label='Own campaign' WHERE id=%s", (self.f.ad_a,))
        self.assertEqual(self.ids(), {str(self.f.ad_a), str(self.f.creative)})
        self.assertEqual(self.ids(self.f.b), {str(self.f.ad_b), str(self.f.creative)})
        payload = self.browse()
        encoded = json.dumps(payload)
        for forbidden in ('Sibling', 'token', 'external_id', 'connection_id', 'snapshot', 'impressions',
                          'performance', 'analysis_error', 'ciphertext', 'https://', 'a-secret',
                          'b-secret', str(self.f.ad_b), str(self.f.unassigned)):
            self.assertNotIn(forbidden, encoded)
        for row in payload['items']:
            self.assertEqual(set(row), {'library_item_id', 'video_id', 'platform', 'content_type',
                                       'published_at', 'analysis_state', 'analyzed', 'display_title', 'summary'})
        self.assertEqual(self.ids(search='Own campaign'), {str(self.f.ad_a)})
        self.assertEqual(self.ids(self.f.b, search='Own campaign'), set())
        for search in ('Sibling', 'a-secret', '%'):
            self.assertEqual(self.ids(search=search), set())
        self.f.link(self.f.a, self.f.fb)
        self.f.db.execute("UPDATE meta_library_items SET label='Sibling campaign private' WHERE id=%s", (self.f.organic,))
        self.assertNotIn('Sibling', json.dumps(self.browse()))

    def test_readiness_matches_current_analysis_without_side_effects(self):
        self.f.link(self.f.a, self.f.fb)
        good_video = self.analyzed(self.f.organic)
        for state in ('deferred', 'discovered', 'queued', 'processing', 'failed', 'unavailable', 'unsupported'):
            item = self.f.item(self.f.fb, state, 'video', 'facebook')
            self.analyzed(item)
            self.f.db.execute('UPDATE meta_library_items SET analysis_state=%s WHERE id=%s', (state, item))
        for reason in ('missing-video', 'stale-item', 'stale-video'):
            item = self.f.item(self.f.fb, reason, 'video', 'facebook')
            video = self.analyzed(item)
            if reason == 'missing-video':
                self.f.db.execute('UPDATE meta_library_items SET video_id=NULL WHERE id=%s', (item,))
            elif reason == 'stale-item':
                self.f.db.execute('UPDATE meta_library_items SET analysis_version=%s WHERE id=%s', (library.ANALYSIS_VERSION + 1, item))
            else:
                self.f.db.execute('UPDATE videos SET analysis_version=%s WHERE id=%s', (library.ANALYSIS_VERSION + 1, video))
        before = self.f.snapshot()
        result = self.browse(analyzed_only=True)
        self.assertEqual([r['library_item_id'] for r in result['items']], [str(self.f.organic)])
        self.assertIsNone(result['next_offset'])
        row = result['items'][0]
        self.assertEqual(row['video_id'], str(good_video))
        self.assertTrue(row['analyzed'])
        self.assertEqual(row['summary'], {'duration_seconds': 5.0, 'width': 1920, 'height': 1080})
        self.assertTrue(all(not r['analyzed'] for r in self.browse()['items'] if r['library_item_id'] != str(self.f.organic)))
        self.assertEqual(before, self.f.snapshot())

    def test_latest_twenty_and_scoping_before_pagination(self):
        self.f.link(self.f.a, self.f.fb)
        self.f.link(self.f.b, self.f.ig)
        for index in range(25):
            item = self.f.item(self.f.ig, f'sibling-{index}', 'reel', 'instagram')
            self.analyzed(item, '2026-09-01T00:00:00Z')
        expected = []
        for index in range(24):
            item = self.f.item(self.f.fb, f'own-{index}', 'video', 'facebook')
            self.analyzed(item, f'2026-01-{index // 2 + 1:02}T00:00:00Z')
            expected.append((index // 2, str(item)))
        ordered = [identity for _, identity in sorted(expected, reverse=True)]
        first = self.browse(analyzed_only=True)
        self.assertEqual([r['library_item_id'] for r in first['items']], ordered[:20])
        self.assertEqual(first['next_offset'], 20)
        self.assertEqual(first, self.browse(analyzed_only=True))
        second = self.browse(analyzed_only=True, offset=first['next_offset'])
        self.assertEqual([r['library_item_id'] for r in second['items']], ordered[20:])
        self.assertIsNone(second['next_offset'])
        self.assertEqual([r['library_item_id'] for r in self.browse(analyzed_only=True, order='asc', limit=100)['items']], list(reversed(ordered)))
        for order in ('asc', 'desc'):
            self.assertEqual(self.browse(order=order, limit=100)['items'][-1]['library_item_id'], str(self.f.organic))
        self.assertEqual(self.browse(analyzed_only=True, offset=100)['items'], [])

    def test_filters_validation_and_empty_results(self):
        self.f.link(self.f.a, self.f.fb)
        self.f.link(self.f.b, self.f.ig)
        self.analyzed(self.f.organic)
        self.analyzed(self.f.instagram)
        self.assertEqual(self.ids(platform='instagram'), set())
        self.assertEqual(self.ids(content_type='reel'), set())
        self.assertEqual(self.ids(platform='facebook', content_type='video', search='FACEBOOK',
                                  published_from='2026-01-01T00:00:00Z', published_to='2026-01-01T00:00:00Z'), {str(self.f.organic)})
        self.assertEqual(self.ids(published_from='2026-01-02T00:00:00Z'), set())
        for params in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'platform': 'tiktok'},
                       {'content_type': 'other'}, {'sort': 'performance'}, {'order': 'bad'},
                       {'analyzed_only': 'bad'}, {'published_from': 'bad'}, {'search': 'x' * 201}):
            response = self.client.get(self.base + '/content', params=params)
            self.assertEqual(response.status_code, 422, response.text)
        self.browse(status=422, published_from='2026-01-01T00:00:00')
        self.browse(status=422, published_from='2026-02-01T00:00:00Z', published_to='2026-01-01T00:00:00Z')

    def test_archived_foreign_and_auth_fail_closed(self):
        for company in (self.f.foreign_company, uuid4()):
            self.browse(company, status=404)
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a)
        self.browse(status=404)
        self.client.cookies.clear()
        self.browse(status=401)

    def test_cross_connection_assets_and_analysis_fail_closed(self):
        self.f.shared_setup()
        foreign = self.f.item(self.f.foreign_ads, 'foreign-asset', 'video', 'facebook', self.f.foreign_connection)
        self.f.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.f.ad_a, foreign))
        self.assertNotIn(str(foreign), self.ids())
        # Simulate a preserved inconsistent V2 FK; 006 uses NOT VALID.
        self.f.db.execute('ALTER TABLE meta_library_items DISABLE TRIGGER ALL')
        video = self.f.db.execute('''INSERT INTO videos(duration_seconds,container,file_size_bytes,meta_connection_id)
            VALUES (8,'mp4',100,%s) RETURNING id''', (self.f.foreign_connection,)).fetchone()['id']
        self.f.db.execute("UPDATE meta_library_items SET video_id=%s,analysis_state='completed',analysis_version=%s WHERE id=%s",
                          (video, library.ANALYSIS_VERSION, self.f.creative))
        self.f.db.execute('ALTER TABLE meta_library_items ENABLE TRIGGER ALL')
        row = next(r for r in self.browse()['items'] if r['library_item_id'] == str(self.f.creative))
        self.assertIsNone(row['video_id'])
        self.assertFalse(row['analyzed'])
        self.assertEqual(row['summary'], {'duration_seconds': None, 'width': None, 'height': None})
        self.assertEqual(self.ids(analyzed_only=True), set())
