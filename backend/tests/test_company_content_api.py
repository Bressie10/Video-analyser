"""Company browsing against real sessions and disposable PostgreSQL."""
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import company_ownership_repository as ownership
from app import meta_library_repository as library
import test_company_api as company_tests
from auth_fixtures import USER_ID


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

    def test_organic_deep_dive_projection_and_scope(self):
        self.f.link(self.f.a, self.f.fb)
        video = self.analyzed(self.f.organic)
        self.f.db.execute("INSERT INTO scenes(video_id,scene_number,start_seconds,end_seconds,duration_seconds) VALUES (%s,1,0,5,5)", (video,))
        self.f.db.execute("INSERT INTO transcript_segments(video_id,segment_index,start_seconds,end_seconds,text) VALUES (%s,0,0.2,1.2,'Hello')", (video,))
        self.f.db.execute("INSERT INTO on_screen_text(video_id,detection_index,text,bounding_box,confidence,appearance_timestamp_seconds,disappearance_timestamp_seconds) VALUES (%s,0,'Offer','{}',0.9,0.4,1.4)", (video,))
        self.f.db.execute("INSERT INTO motion_events(video_id,event_index,start_seconds,end_seconds,type,confidence) VALUES (%s,0,0.5,2,'camera_pan',0.8)", (video,))
        self.f.db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s) ON CONFLICT (item_id) DO UPDATE SET snapshot=EXCLUDED.snapshot',
                          (self.f.organic, json.dumps({'performance_source': 'facebook', 'performance_metrics':
                            {'view_count': 12, 'like_count': None, 'reach': 20, 'provider_url': 'SECRET'}})))
        path = f'/api/companies/{self.f.a}/content/{self.f.organic}/analysis'
        payload = self.request('GET', path, 200)
        self.assertEqual(payload['item']['id'], str(self.f.organic))
        self.assertEqual(payload['scenes'][0]['scene_number'], 1)
        self.assertEqual(payload['transcript'][0]['text'], 'Hello')
        self.assertEqual(payload['ocr'][0]['text'], 'Offer')
        self.assertEqual(payload['motion'][0]['type'], 'camera_pan')
        self.assertEqual(payload['performance'], {'view_count': 12, 'reach': 20})
        self.assertNotIn('SECRET', json.dumps(payload))
        self.request('GET', f'/api/companies/{self.f.a}/content/{self.f.instagram}/analysis', 404)
        self.request('GET', f'/api/companies/{self.f.foreign_company}/content/{self.f.organic}/analysis', 403)
        self.f.db.execute("UPDATE meta_library_items SET analysis_state='processing' WHERE id=%s", (self.f.organic,))
        self.request('GET', path, 404)

    def test_content_media_authorization_and_ranges(self):
        self.f.link(self.f.a, self.f.fb)
        self.analyzed(self.f.organic)
        base = f'/api/companies/{self.f.a}/content/{self.f.organic}'
        self.f.db.execute("UPDATE meta_connections SET status='disconnected' WHERE id=%s", (self.f.connection,))
        self.request('POST', base + '/media-access', 503)
        self.request('POST', f'/api/companies/{self.f.foreign_company}/content/{self.f.organic}/media-access', 403)
        self.request('POST', f'/api/companies/{self.f.a}/content/{self.f.instagram}/media-access', 404)
        self.f.db.execute("UPDATE meta_connections SET status='connected',expires_at=now()+interval '1 day' WHERE id=%s", (self.f.connection,))
        response = self.client.post(base + '/media-access')
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn(base + '/media', response.headers['set-cookie'])
        with patch('app.content_analysis_routes.get_token_verifier', return_value=self.auth.verifier):
            invalid_range = self.client.get(base + '/media', headers={'Range': 'bytes=bad'})
        self.assertEqual(invalid_range.status_code, 416, invalid_range.text)
        with patch('app.content_analysis_routes.get_token_verifier', return_value=self.auth.verifier), \
             patch('app.content_analysis_routes.media_url', return_value='https://video.xx.fbcdn.net/movie'), \
             patch('app.content_analysis_routes._open_media') as opened, \
             patch('app.content_analysis_routes.library.connection_client'):
            class Upstream:
                status_code = 206
                def iter_raw(self, _): yield b'0123456789'
                def close(self): pass
            opened.return_value = (unittest.mock.Mock(), Upstream(), {'Content-Type': 'video/mp4', 'Content-Range': 'bytes 0-9/100'})
            streamed = self.client.get(base + '/media', headers={'Range': 'bytes=0-9'})
            self.assertEqual(streamed.status_code, 206)
            self.assertEqual(streamed.content, b'0123456789')
            opened.assert_called_once_with('https://video.xx.fbcdn.net/movie', 'bytes=0-9')
        self.f.db.execute('DELETE FROM company_accounts WHERE company_id=%s AND account_id=%s', (self.f.a, self.f.fb))
        with patch('app.content_analysis_routes.get_token_verifier', return_value=self.auth.verifier):
            self.assertEqual(self.client.get(base + '/media', headers={'Range': 'bytes=10-19'}).status_code, 404)

    def test_analysis_batch_uses_company_scope_and_owner_permissions(self):
        self.f.link(self.f.a, self.f.fb)
        self.f.link(self.f.b, self.f.ig)
        path = f'/api/companies/{self.f.a}/content/analyze'
        response = self.request('POST', path, 202, json={'item_id': str(self.f.organic)})
        job = self.f.db.execute('SELECT connection_id,kind FROM meta_sync_runs WHERE id=%s',
                                (response['job_id'],)).fetchone()
        self.assertEqual((job['connection_id'], job['kind']), (self.f.connection, 'analysis'))
        self.assertEqual(self.f.db.execute('SELECT analysis_state FROM meta_library_items WHERE id=%s',
                                           (self.f.organic,)).fetchone()['analysis_state'], 'queued')
        self.request('POST', path, 404, json={'item_id': str(self.f.instagram)})
        self.request('POST', path, 404, json={'item_id': str(self.f.unassigned)})
        self.request('POST', f'/api/companies/{self.f.foreign_company}/content/analyze',
                     403, json={'item_id': str(self.f.organic)})
        self.f.db.execute("UPDATE company_memberships SET role='member' WHERE company_id=%s AND user_id=%s",
                          (self.f.a, USER_ID))
        self.request('POST', path, 403, json={'item_id': str(self.f.organic)})

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
                                       'published_at', 'analysis_state', 'analysis_stage',
                                       'analyzed', 'display_title', 'summary'})
        self.assertEqual(self.ids(search='Own campaign'), {str(self.f.ad_a)})
        self.assertEqual(self.ids(self.f.b, search='Own campaign'), set())
        for search in ('Sibling', 'a-secret', '%'):
            self.assertEqual(self.ids(search=search), set())
        self.f.link(self.f.a, self.f.fb)
        self.f.db.execute("UPDATE meta_library_items SET label='Sibling campaign private' WHERE id=%s", (self.f.organic,))
        self.assertNotIn('Sibling', json.dumps(self.browse()))

    def test_initial_bootstrap_is_newest_twenty_and_quota_exempt(self):
        self.f.db.execute('''UPDATE company_billing SET plan_code='free',
            stripe_customer_id=NULL,stripe_subscription_id=NULL,subscription_status=NULL
            WHERE company_id=%s''', (self.f.a,))
        self.f.db.execute('UPDATE meta_accounts SET initialized_at=now() WHERE id=%s', (self.f.fb,))
        for number in range(25):
            self.f.db.execute('''INSERT INTO meta_library_items
                (connection_id,account_id,platform,external_id,content_type,label,published_at)
                VALUES (%s,%s,'facebook',%s,'video','Video',now()-(%s * interval '1 minute'))''',
                (self.f.connection, self.f.fb, str(1000 + number), number))
        self.f.db.execute('''INSERT INTO meta_library_items
            (connection_id,account_id,platform,external_id,content_type,label,published_at)
            VALUES (%s,%s,'facebook','ad-only','ad','Ad',now())''',
            (self.f.connection, self.f.fb))
        self.f.link(self.f.a, self.f.fb)
        batch = self.f.db.execute('''SELECT run_id FROM meta_initial_analysis_batches
            WHERE company_id=%s AND account_id=%s''', (self.f.a, self.f.fb)).fetchone()['run_id']
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM meta_initial_analysis_targets WHERE run_id=%s',
                                           (batch,)).fetchone()['n'], 20)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM meta_jobs WHERE run_id=%s',
                                           (batch,)).fetchone()['n'], 20)
        selected = [row['external_id'] for row in self.f.db.execute('''
            SELECT i.external_id FROM meta_initial_analysis_targets t
            JOIN meta_library_items i ON i.id=t.item_id WHERE t.run_id=%s
            ORDER BY i.published_at DESC''', (batch,)).fetchall()]
        self.assertEqual(selected, [str(1000 + number) for number in range(20)])
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM company_usage_ledger WHERE company_id=%s AND usage_kind=%s',
                                           (self.f.a, 'analysis')).fetchone()['n'], 0)
        library.ensure_initial_analysis_batch(self.f.db, self.f.a, self.f.connection, self.f.fb)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM meta_initial_analysis_batches WHERE company_id=%s',
                                           (self.f.a,)).fetchone()['n'], 1)
        page = self.browse()
        self.assertEqual(page['analysis_progress']['total'], 20)
        self.assertEqual(page['analysis_progress']['queued'], 20)

    def test_link_before_discovery_bootstraps_after_finalization(self):
        self.f.link(self.f.a, self.f.fb)
        self.assertIsNone(self.f.db.execute('''SELECT run_id FROM meta_initial_analysis_batches
            WHERE company_id=%s AND account_id=%s''', (self.f.a, self.f.fb)).fetchone())
        self.f.db.execute('UPDATE meta_accounts SET initial_run_id=%s WHERE id=%s',
                          (self.f.run, self.f.fb))
        library.finalize_runs(self.f.db)
        batch = self.f.db.execute('''SELECT run_id FROM meta_initial_analysis_batches
            WHERE company_id=%s AND account_id=%s''', (self.f.a, self.f.fb)).fetchone()
        self.assertIsNotNone(batch)
        library.finalize_runs(self.f.db)
        self.assertEqual(self.f.db.execute('''SELECT count(*) AS n FROM meta_initial_analysis_batches
            WHERE company_id=%s AND account_id=%s''', (self.f.a, self.f.fb)).fetchone()['n'], 1)

    def test_manual_active_batch_reports_progress_and_reserves_usage(self):
        self.f.link(self.f.a, self.f.fb)
        item = library.item_with_account(self.f.db, self.f.organic)
        library.new_batch(self.f.db, self.f.connection, 'analysis', [item], company_id=self.f.a)
        progress = self.browse()['analysis_progress']
        self.assertEqual((progress['total'], progress['queued'], progress['completed']), (1, 1, 0))
        self.assertEqual(self.f.db.execute('''SELECT count(*) AS n FROM company_usage_ledger
            WHERE company_id=%s AND usage_kind='analysis' AND delta=1''',
            (self.f.a,)).fetchone()['n'], 1)

    def test_claim_and_stage_are_fenced(self):
        from app import meta_library_worker as worker
        self.f.db.execute('UPDATE meta_accounts SET initialized_at=now() WHERE id=%s', (self.f.fb,))
        self.f.link(self.f.a, self.f.fb)
        other = self.f.item(self.f.fb, 'next-video', 'video', 'facebook')
        # The one-time batch was created at link time. A second item queued
        # manually remains waiting while the first claim is processing.
        library.new_batch(self.f.db, self.f.connection, 'analysis',
                          [library.item_with_account(self.f.db, other)], company_id=self.f.a)
        self.assertEqual(self.f.db.execute('''SELECT count(*) AS n FROM company_usage_ledger
            WHERE company_id=%s AND usage_kind='analysis' AND delta=1''',
            (self.f.a,)).fetchone()['n'], 1)
        first = worker.claim_job(analysis=True)
        self.assertIsNotNone(first)
        self.assertEqual(self.f.db.execute('SELECT analysis_state FROM meta_library_items WHERE id=%s',
                                           (first['item_id'],)).fetchone()['analysis_state'], 'processing')
        self.assertEqual(self.f.db.execute('SELECT analysis_state FROM meta_library_items WHERE id=%s',
                                           (other,)).fetchone()['analysis_state'], 'queued')
        for stage in ('downloading', 'inspecting', 'normalizing', 'detecting_scenes',
                      'reading_text', 'detecting_motion', 'extracting_audio',
                      'transcribing', 'saving'):
            worker.analysis_stage(first, stage)
            self.assertEqual(self.f.db.execute('SELECT analysis_stage FROM meta_library_items WHERE id=%s',
                                               (first['item_id'],)).fetchone()['analysis_stage'], stage)
        replacement = {**first, 'claim': uuid4()}
        self.f.db.execute("UPDATE meta_jobs SET claim=%s WHERE id=%s",
                          (replacement['claim'], first['id']))
        worker.analysis_stage(first, 'downloading')
        self.assertEqual(self.f.db.execute('SELECT analysis_stage FROM meta_library_items WHERE id=%s',
                                           (first['item_id'],)).fetchone()['analysis_stage'], 'saving')
        worker.analysis_stage(replacement, 'transcribing')
        self.assertEqual(self.f.db.execute('SELECT analysis_stage FROM meta_library_items WHERE id=%s',
                                           (first['item_id'],)).fetchone()['analysis_stage'], 'transcribing')
        worker.item_status(first['item_id'], 'analysis', 'failed', job=replacement)
        worker.finish(replacement, 'failed')
        self.assertEqual(self.f.db.execute('SELECT analysis_state,analysis_stage FROM meta_library_items WHERE id=%s',
                                           (first['item_id'],)).fetchone(),
                         {'analysis_state': 'failed', 'analysis_stage': None})

    def test_preview_is_authorized_proxied_and_falls_back(self):
        self.f.link(self.f.a, self.f.fb)
        self.browse()
        path = f'/api/companies/{self.f.a}/content/{self.f.organic}/preview'
        with patch('app.content_analysis_routes.library.connection_client', return_value=object()), \
             patch('app.content_analysis_routes.preview_url', return_value='https://x.fbcdn.net/secret') as url, \
             patch('app.content_analysis_routes.preview_bytes', return_value=(b'photo', 'image/jpeg')):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'photo')
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertNotIn('location', response.headers)
        self.assertNotIn('secret', str(response.headers))
        url.assert_called_once()
        self.client.cookies.set('cm_content_preview', self.auth.token(),
                                path=f'/api/companies/{self.f.foreign_company}/content/')
        self.assertEqual(self.client.get(f'/api/companies/{self.f.foreign_company}/content/{self.f.organic}/preview').status_code, 403)
        with patch('app.content_analysis_routes.library.connection_client', return_value=object()), \
             patch('app.content_analysis_routes.preview_url', side_effect=library.meta.MetaError('private')):
            self.assertEqual(self.client.get(path).status_code, 404)

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
            self.browse(company, status=403)
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a)
        self.browse(status=403)
        self.client.headers.pop('Authorization')
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
