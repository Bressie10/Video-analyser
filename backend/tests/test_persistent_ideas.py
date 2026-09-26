"""Actual PostgreSQL/API tests; 006/007 are explicit test-only contract fixtures."""
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import OpenAI, OpenAIError
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from app import idea_repository as ideas, idea_service, meta
from app import meta_library_repository as library
from app.idea_company_access import ProfileEvidence
from app.idea_generation import InvalidGeneration, generate_idea
from app.idea_models import GeneratedIdea, GenerationRequest
from app.main import app
from app.video_repository import save_analysis
from test_recommendations_api import ANALYSIS

ROOT = Path(__file__).resolve().parents[1]
RESULT = GeneratedIdea(title='One idea', concept='A supported exploratory concept', script='Hook. Demo. Close.')


class FixtureAccess:
    """Test-only 006 locking semantics. Production adapter must implement these."""
    def authorize(self, db, session, company_id, item_ids, *, write):
        connection = db.execute('''SELECT c.id FROM meta_connections c JOIN meta_sessions s ON s.connection_id=c.id
            WHERE s.token_hash=%s AND s.expires_at>clock_timestamp() AND c.expires_at>clock_timestamp()
            AND c.status='connected' FOR SHARE OF c,s''', (library.token_hash(session or ''),)).fetchone()
        if not connection:
            raise HTTPException(401, 'Invalid session.')
        member = db.execute('''SELECT * FROM fixture_company_members WHERE company_id=%s
            AND connection_id=%s FOR SHARE''', (company_id, connection['id'])).fetchone()
        if not member or (write and not member['can_write']):
            raise HTTPException(404, 'Company was not found.')
        rows = db.execute('''SELECT item_id FROM fixture_company_items
            WHERE company_id=%s AND item_id=ANY(%s) ORDER BY item_id FOR SHARE''',
            (company_id, item_ids)).fetchall()
        if {row['item_id'] for row in rows} != set(item_ids):
            raise HTTPException(404, 'Content was not found.')

    def profile(self, db, company_id):
        row = db.execute('SELECT * FROM fixture_profiles WHERE company_id=%s', (company_id,)).fetchone()
        return ProfileEvidence(row['revision_id'], row['payload']) if row else None

    def performance(self, db, company_id, item_id):
        return library.public_performance(db, item_id)

    def revalidate(self, db, company_id, capture):
        # This fixture has no distinction between content and metric grants.
        pass


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class PersistentIdeasTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'ideas_' + uuid4().hex
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.admin.execute(f'CREATE SCHEMA {self.schema}')
        self.addCleanup(self.admin.close)
        self.addCleanup(lambda: self.admin.execute(f'DROP SCHEMA {self.schema} CASCADE'))
        self.env = patch.dict(os.environ, {
            'DATABASE_URL': make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={self.schema}', application_name=self.schema),
            'META_TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode(), 'META_WORKER_ENABLED': 'false',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.company, self.other_company, self.connection = uuid4(), uuid4(), uuid4()
        self.session = 'test-session'
        self.profile_id = uuid4()
        self.access = FixtureAccess()
        app.state.idea_company_access = self.access
        self.addCleanup(lambda: delattr(app.state, 'idea_company_access'))
        self.api = TestClient(app, base_url='https://testserver')
        self.api.cookies.set(meta.SESSION_COOKIE, self.session, path='/api/meta')
        self.base = f'/api/meta/companies/{self.company}'
        with library.database() as db:
            for path in sorted((ROOT / 'migrations').glob('00[1-5]_*.sql')):
                db.execute(path.read_text())
            db.execute((ROOT / 'tests/fixtures/idea_company_contract.sql').read_text())
            db.execute((ROOT / 'migrations/008_persistent_ideas.sql').read_text())
            db.execute('INSERT INTO companies VALUES (%s),(%s)', (self.company, self.other_company))
            db.execute('''INSERT INTO meta_connections(id,external_user_id,expires_at)
                VALUES (%s,'provider-user-secret',now()+interval '1 day')''', (self.connection,))
            db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day')",
                       (library.token_hash(self.session), self.connection))
            db.execute('INSERT INTO fixture_company_members VALUES (%s,%s,true)', (self.company, self.connection))
            db.execute('INSERT INTO fixture_profiles VALUES (%s,%s,%s)',
                       (self.company, self.profile_id, Jsonb({'business': 'Coaching'})))
            self.account = db.execute('''INSERT INTO meta_accounts(connection_id,platform,external_id,label)
                VALUES (%s,'facebook','provider-account-secret','Account') RETURNING id''',
                (self.connection,)).fetchone()['id']
        self.sources = [self.add_source() for _ in range(2)]
        self.ad = self.add_source(content_type='ad')
        with library.database() as db:
            for identity in self.sources:
                db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.ad, identity))
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                       (self.ad, Jsonb({'performance_source': 'meta_ads', 'performance_metrics': {'view_count': 42},
                                       'ad_id': 'provider-ad-secret'})))
        self.model = patch('app.idea_service.generate_idea', return_value=RESULT).start()
        self.addCleanup(patch.stopall)

    def add_source(self, content_type='video'):
        with library.database() as db:
            analysis = deepcopy(ANALYSIS)
            analysis.pop('performance_metrics', None)
            analysis.pop('performance_source', None)
            video = save_analysis(analysis, connection=db, video_id=uuid4(), connection_id=self.connection)
            identity = db.execute('''INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,
                content_type,label,video_id,analysis_version,analysis_state,published_at)
                VALUES (%s,%s,'facebook',%s,%s,'Label',%s,1,'completed',now()) RETURNING id''',
                (self.connection, self.account, 'provider-'+uuid4().hex, content_type, video)).fetchone()['id']
            db.execute('INSERT INTO fixture_company_items VALUES (%s,%s)', (self.company, identity))
            return identity

    def body(self, **kwargs):
        return {'request_id': str(uuid4()), 'video_ids': list(map(str, self.sources)), **kwargs}

    def post(self, body=None):
        return self.api.post(self.base+'/recommendations', json=body or self.body(),
                             headers={'X-OpenAI-API-Key': 'request-secret'})

    def generated(self, body=None):
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def evidence(self, identity):
        response = self.api.get(self.base+f'/ideas/{identity}/evidence')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_no_ideas(self):
        with library.database() as db:
            for table in ('ideas', 'idea_sources', 'idea_performance_evidence', 'idea_source_performance', 'idea_target_platforms'):
                self.assertEqual(db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'], 0, table)

    def test_one_idea_exact_evidence_versions_and_shared_metrics(self):
        with patch.dict(os.environ, {'OPENAI_MODEL': 'test-model'}):
            result = self.generated()
        self.assertEqual(result['status'], 'draft')
        self.assertEqual(result['model'], 'test-model')
        self.assertEqual(result['recommendation_version'], 3)
        self.assertEqual(result['evidence_schema_version'], 2)
        self.assertEqual(result['profile_revision_id'], str(self.profile_id))
        evidence = self.evidence(result['id'])
        self.assertEqual(evidence, self.model.call_args.args[0])
        self.assertEqual(len(evidence['performance_snapshots']), 1)
        self.assertEqual(evidence['performance_snapshots'][0]['attribution'], 'shared_ad')
        self.assertEqual([s['source_order'] for s in evidence['videos']], [0, 1])
        for source in evidence['videos']:
            self.assertEqual(source['performance_ids'], [str(self.ad)])
        self.assertNotIn('provider-', json.dumps(evidence))
        with library.database() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 1)
            all_data = str(db.execute('SELECT row_to_json(i) FROM ideas i').fetchall())
            self.assertNotIn('request-secret', all_data)

    def test_retry_same_key_returns_same_idea_even_after_edit_and_unlink(self):
        body = self.body()
        first = self.generated(body)
        self.api.patch(self.base+f"/ideas/{first['id']}", json={'title': 'Edited'})
        with library.database() as db:
            db.execute('DELETE FROM fixture_company_items WHERE company_id=%s', (self.company,))
        second = self.generated(body)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(second['title'], 'Edited')
        self.assertEqual(self.model.call_count, 1)

    def test_changed_request_conflicts(self):
        body = self.body()
        self.generated(body)
        for changes in ({'generation_brief': 'Different'}, {'video_ids': list(reversed(body['video_ids']))},
                        {'target_platforms': ['instagram']}, {'history_limit': 0}):
            response = self.post({**body, **changes})
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.model.call_count, 1)

    def test_failed_request_retains_hash_and_can_retry(self):
        body = self.body()
        self.model.side_effect = OpenAIError('request-secret')
        failure = self.post(body)
        self.assertEqual(failure.status_code, 502)
        self.assertNotIn('request-secret', failure.text)
        self.assert_no_ideas()
        self.model.side_effect = None
        self.assertEqual(self.post({**body, 'generation_brief': 'Changed'}).status_code, 409)
        self.generated(body)

    def test_1_and_20_sources_and_selection_validation(self):
        self.generated(self.body(video_ids=[str(self.sources[0])]))
        twenty = self.sources + [self.add_source() for _ in range(18)]
        self.generated(self.body(video_ids=list(map(str, twenty))))
        for ids in ([], list(map(str, twenty))+[str(uuid4())], [str(self.sources[0])]*2):
            self.assertEqual(self.post(self.body(video_ids=ids)).status_code, 422)

    def test_target_platforms_and_canonical_request_hash(self):
        for targets in ([], ['instagram'], ['facebook'], ['instagram','facebook']):
            body = self.body(target_platforms=targets)
            result = self.generated(body)
            self.assertEqual(result['target_platforms'], sorted(targets))
            self.assertEqual(self.generated({**body, 'target_platforms': list(reversed(targets))})['id'], result['id'])
        for targets in (['tiktok'], ['instagram','instagram']):
            self.assertEqual(self.post(self.body(target_platforms=targets)).status_code, 422)

    def test_frozen_after_refresh_replacement_profile_change_and_unlink(self):
        result = self.generated()
        before = self.evidence(result['id'])
        with library.database() as db:
            db.execute('UPDATE meta_library_performance SET snapshot=%s,fetched_at=now()',
                       (Jsonb({'performance_source': 'meta_ads', 'performance_metrics': {'view_count': 999}}),))
            video = db.execute('SELECT video_id FROM meta_library_items WHERE id=%s', (self.sources[0],)).fetchone()['video_id']
            changed = deepcopy(ANALYSIS)
            changed['audio']['text'] = 'Replacement transcript'
            changed.pop('performance_metrics', None)
            save_analysis(changed, connection=db, video_id=video, analysis_version=2, connection_id=self.connection)
            db.execute('UPDATE fixture_profiles SET revision_id=%s,payload=%s', (uuid4(), Jsonb({'business':'Changed'})))
            db.execute('DELETE FROM fixture_company_items WHERE company_id=%s', (self.company,))
            db.execute('DELETE FROM meta_library_items')
        self.assertEqual(self.evidence(result['id']), before)

    def test_edit_in_place_and_metadata_rejected(self):
        result = self.generated()
        frozen = self.evidence(result['id'])
        endpoint = self.base+f"/ideas/{result['id']}"
        response = self.api.patch(endpoint, json={'title':'New title','concept':'New concept','script':'New script'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['script'], 'New script')
        self.assertGreater(response.json()['updated_at'], result['updated_at'])
        self.assertEqual(self.evidence(result['id']), frozen)
        for invalid in ({}, {'title': None}, {'script': '  '}, {'status':'published'}, {'model':'x'}, {'target_platforms':[]}):
            self.assertEqual(self.api.patch(endpoint, json=invalid).status_code, 422)
        with library.database() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 1)

    def test_company_isolation_and_shared_content(self):
        first = self.generated()
        other = f'/api/meta/companies/{self.other_company}'
        self.assertEqual(self.api.get(other+'/ideas').status_code, 404)
        with library.database() as db:
            db.execute('INSERT INTO fixture_company_members VALUES (%s,%s,true)', (self.other_company, self.connection))
        for suffix in ('', '/evidence'):
            self.assertEqual(self.api.get(other+f"/ideas/{first['id']}"+suffix).status_code, 404)
        self.assertEqual(self.api.patch(other+f"/ideas/{first['id']}", json={'title':'No'}).status_code, 404)
        self.assertEqual(self.api.get(other+'/ideas').json()['items'], [])
        self.assertEqual(self.api.post(other+'/recommendations', json=self.body()).status_code, 404)
        with library.database() as db:
            for identity in [*self.sources, self.ad]:
                db.execute('INSERT INTO fixture_company_items VALUES (%s,%s)', (self.other_company, identity))
        result = self.api.post(other+'/recommendations', json=self.body())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.model.call_args.args[0]['prior_ideas'], [])

    def test_denied_metric_owner(self):
        with library.database() as db:
            db.execute('DELETE FROM fixture_company_items WHERE item_id=%s', (self.ad,))
        self.assertEqual(self.post().status_code, 404)
        self.model.assert_not_called()
        self.assert_no_ideas()

    def test_access_changes_during_generation(self):
        for mutation in ('DELETE FROM fixture_company_items', 'DELETE FROM fixture_company_members', 'DELETE FROM meta_sessions'):
            with self.subTest(mutation=mutation):
                # Restore grants/session between cases.
                with library.database() as db:
                    db.execute('INSERT INTO fixture_company_members VALUES (%s,%s,true) ON CONFLICT DO NOTHING', (self.company,self.connection))
                    db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day') ON CONFLICT DO NOTHING", (library.token_hash(self.session),self.connection))
                    for identity in [*self.sources,self.ad]:
                        db.execute('INSERT INTO fixture_company_items VALUES (%s,%s) ON CONFLICT DO NOTHING', (self.company,identity))
                def revoke(*args, **kwargs):
                    with library.database() as db:
                        db.execute(mutation)
                    return RESULT
                self.model.side_effect = revoke
                self.assertIn(self.post().status_code, (401,404))
                self.assert_no_ideas()

    def test_write_permission_and_missing_adapter(self):
        with library.database() as db:
            db.execute('UPDATE fixture_company_members SET can_write=false')
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.api.get(self.base+'/ideas').status_code, 200)
        app.state.idea_company_access = None
        self.assertEqual(self.post().status_code, 503)
        self.model.assert_not_called()

    def test_history_pagination_and_bounded_prior_inputs(self):
        ids = [self.generated()['id'] for _ in range(3)]
        page = self.api.get(self.base+'/ideas?limit=2').json()
        self.assertEqual([r['id'] for r in page['items']], list(reversed(ids))[:2])
        rest = self.api.get(self.base+'/ideas', params={'limit':2,'after':page['next_cursor']}).json()
        self.assertEqual([r['id'] for r in rest['items']], ids[:1])
        self.assertIsNone(rest['next_cursor'])
        self.generated(self.body(history_limit=1))
        self.assertEqual(len(self.model.call_args.args[0]['prior_ideas']), 1)
        self.generated(self.body(history_limit=0))
        self.assertEqual(self.model.call_args.args[0]['prior_ideas'], [])
        self.assertEqual(self.api.get(self.base+'/ideas', params={'after':str(uuid4())}).status_code, 404)

    def test_mid_insert_failure_rolls_back_all_evidence(self):
        original = ideas.persist
        def broken(db, *args, **kwargs):
            original(db, *args, **kwargs)
            db.execute('SELECT 1/0')
        with patch('app.idea_service.ideas.persist', side_effect=broken):
            self.assertEqual(self.post().status_code, 503)
        self.assert_no_ideas()

    def test_database_seals_evidence_and_generation_metadata(self):
        result = self.generated()
        statements = [
            "UPDATE idea_sources SET analysis_version=99", "DELETE FROM idea_sources",
            "UPDATE idea_performance_evidence SET attribution='ad'", "DELETE FROM idea_performance_evidence",
            "DELETE FROM idea_source_performance", "UPDATE ideas SET model='changed'",
            "UPDATE ideas SET company_id='%s'" % self.other_company,
            "UPDATE ideas SET evidence_sealed=false", "UPDATE ideas SET prior_idea_evidence='[]'::jsonb,request_hash=repeat('0',64)",
            "INSERT INTO idea_target_platforms VALUES ('%s','facebook')" % result['id'],
        ]
        for statement in statements:
            with self.subTest(statement=statement), self.assertRaises(psycopg.IntegrityError):
                with library.database() as db:
                    db.execute(statement)
        request_id = uuid4()
        with library.database() as db:
            db.execute("INSERT INTO idea_generation_requests(company_id,request_id,request_hash) VALUES (%s,%s,repeat('0',64))",
                       (self.company, request_id))
        # This insert is valid immediately; deferred completeness fails at COMMIT.
        with self.assertRaises(psycopg.errors.CheckViolation):
            with library.database() as db:
                db.execute("""INSERT INTO ideas(company_id,title,concept,script,recommendation_version,model,
                    evidence_schema_version,evidence_captured_at,request_id,request_hash,prior_idea_evidence)
                    VALUES (%s,'t','c','s',3,'test',1,now(),%s,repeat('0',64),'[]')""",
                    (self.company, request_id))
        self.assertTrue(db.closed)

    def test_oversized_and_incomplete_evidence(self):
        with library.database() as db:
            db.execute("UPDATE videos SET transcript_text=repeat('x',1100000)")
        self.assertEqual(self.post().status_code, 413)
        self.model.assert_not_called()
        with library.database() as db:
            db.execute("UPDATE meta_library_items SET analysis_state='failed'")
        self.assertEqual(self.post().status_code, 409)
        self.assert_no_ideas()

    def test_concurrent_retry_cannot_generate_or_save_twice(self):
        body = GenerationRequest.model_validate(self.body())
        entered, release = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return RESULT
        self.model.side_effect = delayed
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(idea_service.generate, self.access, self.session, self.company, body)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(HTTPException) as error:
                    idea_service.generate(self.access, self.session, self.company, body)
                self.assertEqual(error.exception.status_code, 409)
            finally:
                release.set()
            first = future.result(timeout=5)
        second = idea_service.generate(self.access, self.session, self.company, body)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.model.call_count, 1)

    def test_consistent_snapshot_during_analysis_replacement(self):
        original = idea_service.read_analysis
        before = deepcopy(ANALYSIS)['audio']['text']
        changed = False
        def replace_after_snapshot(db, video, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                with library.database() as other:
                    other.execute("UPDATE videos SET transcript_text='Concurrent replacement'")
                    other.execute("UPDATE transcript_segments SET text='Concurrent replacement'")
            return original(db, video, **kwargs)
        with patch('app.idea_service.read_analysis', side_effect=replace_after_snapshot):
            result = self.generated()
        for source in self.evidence(result['id'])['videos']:
            self.assertEqual(source['analysis_payload']['audio']['text'], before)

    def test_expired_claim_can_recover_and_old_claim_cannot_save(self):
        body = GenerationRequest.model_validate(self.body())
        digest = idea_service.request_hash(body)
        with library.database() as db:
            claim, _ = ideas.claim_request(db, self.company, body.request_id, digest)
            db.execute("UPDATE idea_generation_requests SET lease_until=now()-interval '1 second'")
        saved = idea_service.generate(self.access, self.session, self.company, body)
        with self.assertRaises(HTTPException) as error, library.database() as db:
            ideas.persist(db, self.company, body, digest, claim, {}, RESULT, 'test', 3, 1)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.generated(body.model_dump(mode='json'))['id'], str(saved['id']))

    def test_authorization_locks_cover_the_final_insert(self):
        original = ideas.persist
        def check_lock(db, *args, **kwargs):
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                with library.database() as other:
                    other.execute("SET LOCAL lock_timeout='50ms'")
                    other.execute('DELETE FROM fixture_company_items WHERE item_id=%s', (self.sources[0],))
            return original(db, *args, **kwargs)
        with patch('app.idea_service.ideas.persist', side_effect=check_lock):
            self.generated()

    def test_no_transaction_during_model_call_and_missing_optional_evidence(self):
        with library.database() as db:
            db.execute('DELETE FROM meta_library_performance')
            db.execute('DELETE FROM fixture_profiles')
        def check_connections(*args, **kwargs):
            count = self.admin.execute('SELECT count(*) FROM pg_stat_activity WHERE application_name=%s',
                                       (self.schema,)).fetchone()[0]
            self.assertEqual(count, 0)
            return RESULT
        self.model.side_effect = check_connections
        result = self.generated()
        evidence = self.evidence(result['id'])
        self.assertEqual(evidence['performance_snapshots'], [])
        self.assertIsNone(evidence['company_profile'])
        self.assertIsNone(result['profile_revision_id'])

    def test_prior_history_is_frozen_after_earlier_idea_edit(self):
        first = self.generated()
        second = self.generated()
        before = self.evidence(second['id'])
        self.assertEqual(before['prior_ideas'][0]['id'], first['id'])
        self.api.patch(self.base+f"/ideas/{first['id']}", json={'title':'Changed earlier idea'})
        self.assertEqual(self.evidence(second['id']), before)

    def test_invalid_model_output_cannot_persist(self):
        self.model.return_value = {'title': 'Title', 'concept': 'Concept'}
        self.assertEqual(self.post().status_code, 502)
        self.assert_no_ideas()



class StructuredGenerationTests(unittest.TestCase):
    @patch('app.idea_generation.OpenAI')
    def test_structured_fields_and_refusal(self, client):
        responses = client.return_value.__enter__.return_value.responses
        responses.parse.return_value = SimpleNamespace(status='completed', output_parsed=RESULT)
        self.assertEqual(generate_idea({'videos': []}, model='test-model', api_key='ephemeral'), RESULT)
        call = responses.parse.call_args.kwargs
        self.assertIs(call['text_format'], GeneratedIdea)
        self.assertFalse(call['store'])
        self.assertEqual(call['model'], 'test-model')
        for response in (SimpleNamespace(status='incomplete',output_parsed=RESULT),
                         SimpleNamespace(status='completed',output_parsed=None)):
            responses.parse.return_value = response
            with self.assertRaises(InvalidGeneration):
                generate_idea({}, model='test-model', api_key='ephemeral')


    def test_real_sdk_structured_response_serialization(self):
        requests = []
        def transport(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                'id': 'resp_test', 'object': 'response', 'created_at': 1,
                'model': 'test-model', 'status': 'completed',
                'output': [{'type': 'message', 'id': 'msg_test', 'role': 'assistant',
                            'status': 'completed', 'content': [{'type': 'output_text',
                            'text': RESULT.model_dump_json(), 'annotations': []}]}],
            })
        def client(**kwargs):
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))
        with patch('app.idea_generation.OpenAI', side_effect=client):
            self.assertEqual(generate_idea({'videos': []}, model='test-model', api_key='ephemeral'), RESULT)
        schema = requests[0]['text']['format']
        self.assertEqual(schema['type'], 'json_schema')
        self.assertTrue(schema['strict'])
        self.assertEqual(set(schema['schema']['required']), {'title', 'concept', 'script'})
        self.assertFalse(requests[0]['store'])
        self.assertNotIn('ephemeral', json.dumps(requests))
