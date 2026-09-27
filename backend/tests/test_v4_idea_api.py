"""V4 HTTP contract on real ownership, profiles, ideas and disposable PostgreSQL."""
import json
import os
import unittest
from uuid import uuid4

from app import company_ownership_repository as ownership
import test_idea_integration as integration


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class V4IdeaAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration.IdeaIntegrationTests('test_real_adapter_shared_creative_and_profile_revisions')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.f = self.fixture.f
        self.client = self.fixture.client
        self.base = f'/api/meta/companies/{self.f.a}'

    def generate(self, **overrides):
        return self.fixture.generate(body={
            'request_id': str(uuid4()), 'video_ids': [str(self.f.creative)],
            'target_platforms': ['instagram', 'facebook'], **overrides,
        })

    def history(self, **params):
        response = self.client.get(self.base + '/ideas', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_required_explicit_sources_and_supported_targets(self):
        base = {'request_id': str(uuid4()), 'video_ids': [str(self.f.creative)],
                'target_platforms': ['instagram']}
        invalid = [dict(base, video_ids=[]), dict(base, video_ids=[str(uuid4()) for _ in range(21)]),
                   dict(base, target_platforms=[]), dict(base, target_platforms=['meta_ads']),
                   dict(base, target_platforms=['tiktok']), dict(base, target_platforms=['facebook']*2)]
        invalid.extend({k:v for k,v in base.items() if k != missing}
                       for missing in ('request_id', 'video_ids', 'target_platforms'))
        for body in invalid:
            response = self.client.post(self.base + '/recommendations', json=body)
            self.assertEqual(response.status_code, 422, response.text)
        self.fixture.model.assert_not_called()
        for targets in (['instagram'], ['facebook'], ['facebook','instagram']):
            saved = self.generate(target_platforms=targets)
            self.assertEqual(saved['target_platforms'], sorted(targets))
            detail = self.client.get(self.base + '/ideas/' + saved['id'])
            self.assertEqual(detail.json(), saved)

    def test_twenty_owned_explicit_sources_persist_once_and_retry(self):
        ids = [self.f.creative]
        for _ in range(19):
            identity = self.f.item(self.f.fb, uuid4().hex, 'video', 'facebook')
            self.f.db.execute("""UPDATE meta_library_items SET video_id=%s,
                analysis_state='completed',analysis_version=1 WHERE id=%s""", (self.f.video, identity))
            self.f.db.execute('DELETE FROM meta_library_performance WHERE item_id=%s', (identity,))
            ids.append(identity)
        body = {'request_id': str(uuid4()), 'video_ids': list(map(str, ids)),
                'target_platforms': ['facebook'], 'generation_brief': 'Make one clear demo.'}
        first = self.fixture.generate(body=body)
        self.assertEqual(self.fixture.generate(body=body), first)
        self.assertEqual(self.fixture.model.call_count, 1)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 1)
        evidence = self.client.get(self.base + '/ideas/' + first['id'] + '/evidence').json()
        self.assertEqual([v['library_item_id'] for v in evidence['videos']], body['video_ids'])
        self.assertEqual(self.fixture.post(body={**body, 'generation_brief': 'Different'}).status_code, 409)

    def test_history_filters_and_filtering_before_pagination(self):
        first = self.generate(target_platforms=['instagram'])
        second = self.generate(target_platforms=['instagram','facebook'])
        newest = self.generate(target_platforms=['facebook'])
        for saved, title in ((first, 'Needle title'), (second, 'Other title')):
            response = self.client.patch(self.base + '/ideas/' + saved['id'], json={
                'title': title, 'concept': 'New concept', 'script': 'needle in saved script', 'status': 'used'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.put(self.base + '/ideas/' + saved['id'] + '/feedback',
                json={'feedback':'disliked', 'reason':'Too familiar'}).status_code, 200)
        sibling = self.fixture.generate(company=self.f.b)
        cases = [({'search':'NEEDLE'}, [second, first]), ({'search':'new concept'}, [second, first]),
                 ({'search':'Needle title'}, [first]), ({'search':"%' OR true --"}, []),
                 ({'status':'used'}, [second, first]), ({'feedback':'disliked'}, [second, first]),
                 ({'feedback':'none'}, [newest]), ({'target_platform':'instagram'}, [second, first]),
                 ({'target_platform':'facebook'}, [newest, second]),
                 ({'created_from':first['created_at'], 'created_to':newest['created_at']}, [second, first])]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                page = self.history(**filters, limit=1)
                found = page['items']
                while page['next_cursor']:
                    page = self.history(**filters, limit=1, after=page['next_cursor'])
                    found += page['items']
                self.assertEqual([i['id'] for i in found], [i['id'] for i in expected])
                for row in found:
                    self.assertIn('target_platforms', row)
        combined = dict(search='needle', status='used', feedback='disliked', target_platform='instagram',
                        created_from=first['created_at'], created_to=newest['created_at'])
        self.assertEqual([i['id'] for i in self.history(**combined)['items']], [second['id'],first['id']])
        self.assertEqual(self.client.get(self.base + '/ideas', params={'after':sibling['id']}).status_code, 404)

    def test_invalid_history_filters(self):
        for params in ({'status':'scheduled'}, {'feedback':'love'}, {'target_platform':'meta_ads'},
                       {'limit':0}, {'limit':101}, {'after':'invalid'}, {'search':'x'*201},
                       {'created_from':'2026-01-01T00:00:00'}, {'created_to':'bad'},
                       {'created_from':'2026-02-01T00:00:00Z', 'created_to':'2026-01-01T00:00:00Z'}):
            self.assertEqual(self.client.get(self.base + '/ideas', params=params).status_code, 422)

    def test_save_lifecycle_feedback_and_publications_preserve_evidence(self):
        saved = self.generate()
        base = self.base + '/ideas/' + saved['id']
        evidence = self.client.get(base + '/evidence').json()
        changed = self.client.patch(base, json={'title':'Saved title','concept':'Saved concept','script':'Saved script'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()['script'], 'Saved script')
        self.assertEqual(self.client.patch(base, json={'status':'published'}).json()['status'], 'published')
        for feedback, reason in (('disliked', '  Wrong tone  '), ('liked', None), ('none', None)):
            result = self.client.put(base + '/feedback', json={'feedback':feedback,'reason':reason})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['feedback_reason'], reason.strip() if reason else None)
        for identity in (self.f.organic, self.f.instagram):
            self.assertEqual(self.client.put(base + '/publications/' + str(identity)).status_code, 200)
        linked = self.client.get(base + '/publications')
        self.assertEqual(linked.status_code, 200)
        self.assertEqual({p['library_item_id'] for p in linked.json()['items']},
                         {str(self.f.organic),str(self.f.instagram)})
        for row in linked.json()['items']:
            self.assertEqual(set(row), {'library_item_id','created_at'})
        ownership.unlink_account(self.f.db, self.f.connection, self.f.a, self.f.fb)
        self.assertEqual(self.client.get(base + '/publications').json(), linked.json())
        self.assertEqual(self.client.put(base + '/publications/' + str(self.f.organic)).status_code, 404)
        self.assertEqual(self.client.delete(base + '/publications/' + str(self.f.organic)).status_code, 200)
        self.assertEqual(len(self.client.get(base + '/publications').json()['items']), 1)
        self.assertEqual(self.client.get(base + '/evidence').json(), evidence)

    def test_publication_picker_scope_pagination_and_live_revocation(self):
        # Shared creative has a date but must not expose sibling metadata.
        self.f.db.execute('UPDATE meta_library_items SET published_at=now()')
        self.f.db.execute("UPDATE meta_library_items SET label='URL https://provider.example/secret' WHERE id=%s",
                          (self.f.organic,))
        undated = self.f.item(self.f.fb, 'undated', 'video', 'facebook')
        first = self.client.get(self.base + '/publication-options', params={'limit':1})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.get(self.base + '/publication-options',
                                 params={'limit':1,'after':first.json()['next_cursor']})
        items = first.json()['items'] + second.json()['items']
        self.assertEqual({i['id'] for i in items}, {str(self.f.organic),str(self.f.instagram)})
        self.assertIsNone(second.json()['next_cursor'])
        for item in items:
            self.assertEqual(set(item), {'id','platform','content_type','label','published_at'})
        for identity in (undated, self.f.creative, self.f.ad_b, self.fixture.fixture.b_facebook, self.f.foreign_ad, uuid4()):
            self.assertEqual(self.client.get(self.base + '/publication-options',
                                            params={'after':str(identity)}).status_code, 404)
        self.assertNotIn('secret', json.dumps(items))
        self.assertEqual([item['label'] for item in items], ['Published post', 'Published post'])
        ownership.unlink_account(self.f.db, self.f.connection, self.f.a, self.f.fb)
        current = self.client.get(self.base + '/publication-options').json()['items']
        self.assertEqual([i['id'] for i in current], [str(self.f.instagram)])
        self.assertEqual(self.client.get(self.base + '/publication-options',
                                        params={'after':str(self.f.organic)}).status_code, 404)

    def test_publication_picker_suppresses_legacy_sibling_ad_labels(self):
        # Discovery can overwrite an owned organic video's legacy label with
        # the name of a sibling company's ad that uses it as a creative.
        self.f.db.execute("UPDATE meta_library_items SET published_at=now(),label='Sibling campaign private' WHERE id=%s", (self.f.organic,))
        self.f.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.f.ad_b, self.f.organic))
        for linked in (True, False):
            response = self.client.get(self.base + '/publication-options')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(str(self.f.organic), response.text)
            self.assertNotIn('Sibling campaign private', response.text)
            if linked:
                # Removing the edge does not clean contaminated historical labels.
                self.f.db.execute('DELETE FROM meta_ad_assets WHERE video_item_id=%s', (self.f.organic,))

    def test_archive_and_sibling_deny_every_mutation_and_new_reads(self):
        saved = self.generate()
        base = self.base + '/ideas/' + saved['id']
        self.client.put(base + '/publications/' + str(self.f.organic))
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a)
        for company in (self.f.a, self.f.b, self.f.foreign_company):
            endpoint = f'/api/meta/companies/{company}/ideas/{saved["id"]}'
            for response in (
                self.client.patch(endpoint, json={'title':'No'}),
                self.client.patch(endpoint, json={'status':'used'}),
                self.client.put(endpoint + '/feedback', json={'feedback':'liked'}),
                self.client.put(endpoint + '/publications/' + str(self.f.instagram)),
                self.client.delete(endpoint + '/publications/' + str(self.f.organic)),
                self.client.get(endpoint), self.client.get(endpoint + '/publications'),
            ):
                self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.fixture.post().status_code, 404)
        self.assertEqual(self.client.get(self.base + '/ideas').status_code, 404)
        self.assertEqual(self.client.get(self.base + '/publication-options').status_code, 404)
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a, archived=False)
        self.assertEqual(self.client.get(base).json()['title'], saved['title'])
        self.assertEqual(len(self.client.get(base + '/publications').json()['items']), 1)

    def test_signed_out_new_reads_fail_closed(self):
        saved = self.generate()
        self.client.cookies.clear()
        for path in ('/ideas', '/publication-options', '/ideas/' + saved['id'] + '/publications'):
            self.assertEqual(self.client.get(self.base + path).status_code, 401)
