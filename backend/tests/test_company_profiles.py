"""Real company ownership, stubbed model, PostgreSQL concurrency and API tests."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import company_profile_repository as repo
from app import company_profile_evidence as evidence
from app import company_profile_worker as worker
from app import company_profile_types as policy
from app.company_profile_company import OwnershipCompanyAdapter, bind_company_adapter, get_company_adapter
from app import company_ownership_repository as ownership
from app import meta
from app import meta_library_repository as library
from app.company_profile_generator import OpenAIProfileGenerator, InvalidProfile, validate
from app.company_profile_types import ProfileDocument
from app.company_profile_routes import router


class FakeGenerator:
    model = 'test-profile-model'
    input_overhead = OpenAIProfileGenerator.input_overhead

    def __init__(self):
        self.calls, self.callback, self.failure = [], None, None

    def generate(self, payload):
        self.calls.append(deepcopy(payload))
        if self.callback:
            self.callback()
        if self.failure:
            raise self.failure
        ref = next(iter(evidence.references(payload)))
        return ProfileDocument(topics=[policy.Claim(
            text='Observed topic', evidence_refs=[ref], comparison_basis='Stored content sample',
            evidence_kind='content', confidence='low', supporting_count=999,
        )], confidence='low').model_dump()


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyProfileTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'company_profiles_' + uuid4().hex
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_db)
        url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={self.schema}')
        env = patch.dict(os.environ, {'DATABASE_URL': url, 'COMPANY_PROFILE_WORKER_ENABLED': 'false'})
        env.start()
        self.addCleanup(env.stop)
        migrations = Path(__file__).resolve().parents[1] / 'migrations'
        with repo.database() as db:
            for path in sorted(migrations.glob('*.sql')):
                db.execute(path.read_text())
            self.connection = db.execute('''INSERT INTO meta_connections(external_user_id,expires_at)
                VALUES ('shared-connection',now()+interval '1 day') RETURNING id''').fetchone()['id']
            self.company = ownership.create_company(db, self.connection, 'Company')['id']
            self.other = ownership.create_company(db, self.connection, 'Other')['id']
            self.session = 'test-persisted-profile-session'
            db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day')",
                       (library.token_hash(self.session), self.connection))
            self.account = self.add_account(db, self.company, 'instagram')
            self.other_account = self.add_account(db, self.other, 'instagram')
            self.item = self.add_item(db, self.account)
            self.other_item = self.add_item(db, self.other_account, label='PRIVATE OTHER COMPANY')
        self.adapter = OwnershipCompanyAdapter()
        previous_adapter = get_company_adapter()
        bind_company_adapter(self.adapter)
        self.addCleanup(bind_company_adapter, previous_adapter)
        self.generator = FakeGenerator()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.client.cookies.set(meta.SESSION_COOKIE, self.session, path='/api')
        self.headers = {}
        self.base = f'/api/companies/{self.company}/profiles'

    def cleanup_db(self):
        self.admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.admin.close()

    def add_account(self, db, company, platform):
        account = db.execute('''INSERT INTO meta_accounts(connection_id,platform,external_id,label)
            VALUES (%s,%s,%s,'fixture') RETURNING id''', (self.connection, platform, str(uuid4()))).fetchone()['id']
        # Seed fixture ownership without scheduling refreshes. Mutation tests below
        # exercise the transactional service hooks on top of this initial state.
        db.execute('''INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
            VALUES (%s,%s,%s,%s)''', (company, self.connection, account, platform))
        return account

    def add_item(self, db, account, platform='instagram', *, label='Fixture topic', analyzed=True, ad=False):
        item = uuid4()
        if analyzed:
            db.execute('''INSERT INTO videos(id,duration_seconds,container,file_size_bytes,transcript_text,meta_connection_id)
                VALUES (%s,10,'mp4',100,%s,%s)''', (item, label, self.connection))
        db.execute('''INSERT INTO meta_library_items
            (id,connection_id,account_id,platform,external_id,content_type,label,published_at,analysis_state,analysis_version,video_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s)''',
            (item, self.connection, account, platform, str(item), 'ad' if ad else 'video', label,
             'completed' if analyzed else 'deferred', 1 if analyzed else None, item if analyzed else None))
        if ad:
            owner = db.execute("""SELECT company_id FROM company_accounts
                WHERE account_id=%s AND account_platform='meta_ads'""", (account,)).fetchone()
            if owner:
                db.execute("""INSERT INTO company_ad_assignments(ad_item_id,company_id,connection_id,account_id)
                    VALUES (%s,%s,%s,%s)""", (item, owner['company_id'], self.connection, account))
        return item

    def refresh(self, scope='instagram', key=None):
        response = self.client.post(self.base + '/' + scope + '/refresh',
                                    headers={**self.headers, 'Idempotency-Key': key or str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def process(self):
        job = repo.claim()
        self.assertIsNotNone(job)
        worker.process_job(job, self.adapter, self.generator)
        with repo.database() as db:
            result = db.execute('SELECT * FROM company_profile_jobs WHERE id=%s', (job['id'],)).fetchone()
        self.assertNotEqual(result['state'], 'failed', result)
        return result

    def read(self, scope='instagram'):
        response = self.client.get(self.base + '/' + scope, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def invalidate(self, reason='analysis_changed', scopes=('instagram',), key=None):
        with repo.database() as db:
            return repo.invalidate(db, self.company, scopes, reason, event_key=key)

    def build_first(self):
        self.refresh()
        self.process()
        return self.read()

    def test_read_is_pure_and_unbound_fails_closed(self):
        self.assertEqual(self.read()['freshness'], 'missing')
        with repo.database() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM company_profiles').fetchone()['n'], 0)
        bind_company_adapter(None)
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 503)

    def test_platform_revision_freshness_and_force_unchanged(self):
        before = self.build_first()
        self.assertEqual(before['freshness'], 'fresh')
        self.assertEqual(before['document']['topics'][0]['supporting_count'], 1)
        self.refresh(key='unchanged')
        self.assertEqual(self.read()['freshness'], 'fresh')
        self.assertEqual(self.process()['outcome'], 'reused')
        self.assertEqual(len(self.generator.calls), 1)
        self.assertEqual(self.read()['revision']['id'], before['revision']['id'])
        self.invalidate()
        self.assertEqual(self.read()['freshness'], 'stale')
        self.process()
        self.assertEqual(self.read()['freshness'], 'fresh')
        self.assertEqual(len(self.generator.calls), 1)

    def test_force_idempotency_coalesces_and_replays_finished_job(self):
        first = self.refresh(key='same')
        self.assertEqual(self.refresh(key='same')['job_id'], first['job_id'])
        self.assertEqual(self.refresh(key='other')['job_id'], first['job_id'])
        self.process()
        self.assertEqual(self.refresh(key='same')['job_id'], first['job_id'])
        self.assertNotEqual(self.refresh(key='new')['job_id'], first['job_id'])
        self.assertEqual(self.client.post(self.base + '/instagram/refresh', headers=self.headers).status_code, 422)

    def test_shared_consumes_only_platform_revisions(self):
        self.refresh('shared')
        for _ in range(4):
            self.process()
        shared = self.read('shared')
        self.assertEqual(shared['freshness'], 'fresh')
        call = self.generator.calls[-1]
        self.assertEqual(call['scope'], 'shared')
        self.assertEqual(call['items'], [])
        self.assertEqual(call['performances'], [])
        self.assertEqual(len(call['platform_profiles']), 3)
        self.assertEqual(set(shared['revision']['dependencies']), set(policy.PLATFORMS))
        self.assertEqual(len(self.generator.calls), 2)

    def test_concurrent_invalidations_are_not_lost_and_events_deduplicate(self):
        self.build_first()
        barrier = threading.Barrier(6)
        def event(index):
            barrier.wait()
            return self.invalidate(key=f'event-{index}')
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertTrue(all(pool.map(event, range(6))))
        self.assertEqual(self.read()['input_revision'], 7)
        self.assertFalse(self.invalidate(key='event-0'))
        self.assertEqual(self.read()['input_revision'], 7)
        with repo.database() as db:
            self.assertEqual(db.execute('''SELECT count(*) AS n FROM company_profile_jobs j
                JOIN company_profiles p ON p.id=j.profile_id WHERE p.scope='instagram'
                AND j.state IN ('queued','running')''').fetchone()['n'], 1)

    def test_concurrent_refreshes_share_one_job(self):
        def enqueue(index):
            with repo.database() as db:
                return repo.refresh(db, self.company, 'instagram', str(index))['job_id']
        with ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(pool.map(enqueue, range(10)))
        self.assertEqual(len(set(ids)), 1)

    def test_expired_lease_recovered_and_old_worker_fenced(self):
        self.refresh()
        old = repo.claim()
        with repo.database() as db:
            db.execute("UPDATE company_profile_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (old['id'],))
        self.assertFalse(repo.renew(old))
        new = repo.claim()
        self.assertEqual(new['id'], old['id'])
        self.assertNotEqual(new['claim'], old['claim'])
        worker.process_job(old, self.adapter, self.generator)
        self.assertEqual(len(self.generator.calls), 0)
        worker.process_job(new, self.adapter, self.generator)
        self.assertEqual(self.read()['freshness'], 'fresh')

    def test_generation_input_change_discards_result_and_requeues(self):
        self.refresh()
        self.generator.callback = self.invalidate
        self.assertEqual(self.process()['state'], 'queued')
        self.assertEqual(self.read()['freshness'], 'missing')
        self.generator.callback = None
        with repo.database() as db:
            db.execute("UPDATE company_profile_jobs SET available_at=now() WHERE state='queued'")
        self.process()
        self.assertEqual(self.read()['freshness'], 'fresh')

    def test_assignment_change_during_generation_is_fenced(self):
        self.refresh()
        def change():
            with repo.database() as db:
                ownership.unlink_account(db, self.connection, self.company, self.account)
        self.generator.callback = change
        self.assertEqual(self.process()['state'], 'queued')
        self.assertFalse(self.read()['usable'])

    def test_failed_generation_preserves_previous_revision(self):
        prior = self.build_first()
        with repo.database() as db:
            db.execute("UPDATE videos SET transcript_text='Changed analysis' WHERE id=%s", (self.item,))
            repo.invalidate(db, self.company, ['instagram'], 'analysis_changed')
        self.generator.failure = InvalidProfile('bad model output')
        worker.process_job(repo.claim(), self.adapter, self.generator)
        after = self.read()
        self.assertTrue(after['usable'])
        self.assertEqual(after['freshness'], 'stale')
        self.assertEqual(after['job']['state'], 'failed')
        self.assertEqual(after['revision']['id'], prior['revision']['id'])

    def test_transient_failure_backoff_is_bounded(self):
        self.refresh()
        self.generator.failure = RuntimeError('provider secret must never persist')
        for attempt in range(1, 4):
            worker.process_job(repo.claim(), self.adapter, self.generator)
            result = self.read()['job']
            self.assertEqual(result['attempts'], attempt)
            self.assertEqual(result['state'], 'failed' if attempt == 3 else 'queued')
            self.assertNotIn('secret', result['error'])
            with repo.database() as db:
                db.execute("UPDATE company_profile_jobs SET available_at=now() WHERE state='queued'")

    def test_partial_evidence_does_not_analyze_deferred_history(self):
        with repo.database() as db:
            deferred = self.add_item(db, self.account, analyzed=False)
        self.build_first()
        call = self.generator.calls[0]
        self.assertEqual(call['coverage']['available_items'], 2)
        self.assertIsNone(next(i for i in call['items'] if i['id'] == str(deferred))['analysis'])
        with repo.database() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM meta_jobs').fetchone()['n'], 0)

    def test_cross_company_api_and_evidence_isolation_same_connection(self):
        self.build_first()
        self.assertNotIn('PRIVATE OTHER COMPANY', evidence.encoded(self.generator.calls))
        self.assertNotIn(str(self.other_item), evidence.encoded(self.generator.calls))
        for suffix in ('', '/instagram'):
            response = self.client.get(f'/api/companies/{self.other}/profiles' + suffix, headers=self.headers)
            # One authenticated connection may manage both companies.
            self.assertEqual(response.status_code, 200)
        response = self.client.post(f'/api/companies/{self.other}/profiles/instagram/refresh',
                                    headers={**self.headers, 'Idempotency-Key': 'x'})
        self.assertEqual(response.status_code, 202)

    def test_paid_metrics_deduplicated_and_context_preserved(self):
        with repo.database() as db:
            ads_account = self.add_account(db, self.company, 'meta_ads')
            ad = self.add_item(db, ads_account, 'meta_ads', analyzed=False, ad=True)
            second = self.add_item(db, self.account)
            db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s),(%s,%s)', (ad, self.item, ad, second))
            snapshot = {'performance_source': 'meta_ads', 'performance_metrics': {
                'view_count': None, 'like_count': 0, 'meta_ads': {'currency': 'EUR',
                'date_start': '2026-01-01', 'date_stop': '2026-01-07', 'attribution_windows': ['7d_click']}}}
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)', (ad, Jsonb(snapshot)))
            private_ad = self.add_item(db, self.other_account, analyzed=False, ad=True)
            db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (private_ad, self.item))
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                       (private_ad, Jsonb({'private': 'OTHER'})))
        self.build_first()
        metrics = self.generator.calls[-1]['performances']
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]['snapshot'], snapshot)
        self.assertEqual(metrics[0]['attribution'], 'shared_ad')
        self.assertEqual(metrics[0]['asset_count'], 2)
        self.refresh('meta_ads')
        self.process()
        self.assertEqual(len(self.generator.calls[-1]['performances']), 1)
        self.assertEqual(len(self.generator.calls[-1]['items']), 2)

    def test_fetch_time_only_change_skips_generation(self):
        with repo.database() as db:
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                       (self.item, Jsonb({'performance_metrics': {'view_count': None, 'like_count': 0}})))
        self.build_first()
        with repo.database() as db:
            db.execute('UPDATE meta_library_performance SET fetched_at=now() WHERE item_id=%s', (self.item,))
        self.refresh()
        self.process()
        self.assertEqual(len(self.generator.calls), 1)

    def test_revisions_immutable_and_pointer_cannot_cross_profiles(self):
        self.build_first()
        with self.assertRaises(psycopg.Error), repo.database() as db:
            db.execute("UPDATE company_profile_revisions SET model='changed'")
        with self.assertRaises(psycopg.Error), repo.database() as db:
            db.execute('DELETE FROM company_profile_revisions')
        with self.assertRaises(psycopg.Error), repo.database() as db:
            db.execute('''UPDATE company_profiles SET current_revision_id=(SELECT id FROM company_profile_revisions LIMIT 1)
                WHERE scope='facebook' ''')

    def test_removal_suppresses_platform_and_shared_immediately(self):
        self.refresh('shared')
        for _ in range(4):
            self.process()
        self.assertTrue(self.read('shared')['usable'])
        self.invalidate('evidence_removed')
        self.assertFalse(self.read()['usable'])
        self.assertFalse(self.read('shared')['usable'])
        self.assertNotIn('document', self.read())

    def test_generator_schema_upgrade_invalidates(self):
        self.build_first()
        with patch.object(policy, 'GENERATOR_VERSION', 'next'):
            self.assertEqual(self.read()['freshness'], 'stale')
            repo.schedule_versions()
            for _ in range(3):
                self.process()
            self.assertEqual(self.read()['freshness'], 'fresh')
            self.assertEqual(len(self.generator.calls), 2)

    def test_effective_input_budget_and_selection_are_deterministic(self):
        with repo.database() as db:
            for _ in range(policy.MAX_ITEMS + 3):
                self.add_item(db, self.account, label='long ' * 1000)
            one = evidence.assemble(db, self.company, 'instagram', self.adapter, overhead=self.generator.input_overhead)
            two = evidence.assemble(db, self.company, 'instagram', self.adapter, overhead=self.generator.input_overhead)
        self.assertEqual(one, two)
        self.assertLessEqual(len(evidence.encoded(one['payload']).encode()) + self.generator.input_overhead, policy.MAX_INPUT_BYTES)
        self.assertLessEqual(len(one['payload']['items']), policy.MAX_ITEMS)
        self.assertTrue(one['payload']['coverage']['input_truncated'])

    def test_new_invalidation_survives_a_failing_old_build(self):
        self.refresh()
        self.generator.callback = self.invalidate
        self.generator.failure = InvalidProfile('old failure')
        job = repo.claim()
        worker.process_job(job, self.adapter, self.generator)
        self.assertEqual(self.read()['job']['state'], 'queued')
        self.assertEqual(self.read()['job']['attempts'], 0)

    def test_shared_skips_call_after_unchanged_platform_invalidation(self):
        self.refresh('shared')
        for _ in range(4):
            self.process()
        old_id = self.read('shared')['revision']['id']
        calls = len(self.generator.calls)
        self.invalidate()
        self.process()
        self.process()
        self.assertEqual(len(self.generator.calls), calls)
        self.assertEqual(self.read('shared')['revision']['id'], old_id)
        self.assertEqual(self.read('shared')['freshness'], 'fresh')

    def test_shared_evidence_registry_deduplicates_shared_ad_context(self):
        with repo.database() as db:
            ads_account = self.add_account(db, self.company, 'meta_ads')
            ad = self.add_item(db, ads_account, 'meta_ads', analyzed=False, ad=True)
            db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (ad, self.item))
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                (ad, Jsonb({'performance_source': 'meta_ads', 'performance_metrics': {
                    'view_count': 5, 'meta_ads': {'account_currency': 'EUR', 'date_start': '2026-01-01',
                    'date_stop': '2026-01-07', 'action_attribution_windows': ['7d_click']}}})))
        self.refresh('shared')
        for _ in range(4):
            self.process()
        payload = self.generator.calls[-1]
        ref = 'performance:' + str(ad)
        self.assertEqual(sum(key == ref for key in payload['evidence_registry']), 1)
        self.assertEqual(payload['evidence_registry'][ref]['context']['account_currency'], 'EUR')
        self.assertTrue(all('evidence' not in row for row in payload['platform_profiles']))

    def test_recovered_lease_attempt_limit(self):
        self.refresh()
        for _ in range(policy.MAX_ATTEMPTS):
            job = repo.claim()
            self.assertIsNotNone(job)
            with repo.database() as db:
                db.execute("UPDATE company_profile_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job['id'],))
        self.assertIsNone(repo.claim())
        self.assertEqual(self.read()['job']['state'], 'failed')

    def test_missing_all_evidence_skips_model_including_shared(self):
        with repo.database() as db:
            db.execute('DELETE FROM company_accounts WHERE company_id=%s', (self.company,))
        self.refresh('shared')
        for _ in range(4):
            self.process()
        self.assertEqual(self.generator.calls, [])
        self.assertEqual(self.read('shared')['document']['confidence'], 'insufficient')

    def test_parallel_claims_only_one_worker_owns_the_profile(self):
        self.refresh()
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: repo.claim(), range(4)))
        self.assertEqual(sum(job is not None for job in claims), 1)

    def test_lease_lost_during_model_call_cannot_publish(self):
        self.refresh()
        job = repo.claim()
        recovered = []
        def reclaim():
            with repo.database() as db:
                db.execute("UPDATE company_profile_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job['id'],))
            recovered.append(repo.claim())
        self.generator.callback = reclaim
        worker.process_job(job, self.adapter, self.generator)
        self.assertEqual(self.read()['freshness'], 'missing')
        self.generator.callback = None
        worker.process_job(recovered[0], self.adapter, self.generator)
        self.assertEqual(self.read()['revision']['revision_number'], 1)

    def test_shared_build_discarded_when_dependency_changes(self):
        self.refresh('shared')
        for _ in range(3):
            self.process()
        def replace():
            self.invalidate()
        self.generator.callback = replace
        self.assertEqual(self.process()['state'], 'queued')
        self.assertEqual(self.read('shared')['freshness'], 'missing')

    def test_analysis_replacement_creates_second_immutable_revision(self):
        old = self.build_first()
        with repo.database() as db:
            db.execute("UPDATE videos SET transcript_text='Replacement' WHERE id=%s", (self.item,))
            repo.invalidate(db, self.company, ['instagram'], 'analysis_changed')
        self.process()
        new = self.read()
        self.assertEqual(new['revision']['revision_number'], 2)
        self.assertNotEqual(old['revision']['id'], new['revision']['id'])
        with repo.database() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM company_profile_revisions').fetchone()['n'], 2)

    def test_material_metrics_and_relationship_changes_invalidate(self):
        self.build_first()
        with repo.database() as db:
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                       (self.item, Jsonb({'performance_source': 'instagram', 'performance_metrics': {'view_count': 100}})))
            repo.invalidate(db, self.company, ['instagram'], 'performance_changed')
        self.process()
        self.assertEqual(len(self.generator.calls), 2)
        with repo.database() as db:
            ad_account = self.add_account(db, self.company, 'meta_ads')
            ad = self.add_item(db, ad_account, 'meta_ads', analyzed=False, ad=True)
            db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                       (ad, Jsonb({'performance_source': 'meta_ads', 'performance_metrics': {'view_count': 20}})))
            db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (ad, self.item))
            repo.invalidate(db, self.company, ['instagram', 'meta_ads'], 'relationship_changed')
        self.process()
        self.assertEqual(len(self.generator.calls), 3)

    def test_transaction_rollback_does_not_invalidate(self):
        self.build_first()
        with self.assertRaises(RuntimeError), repo.database() as db:
            repo.invalidate(db, self.company, ['instagram'], 'new_content')
            raise RuntimeError('roll back source mutation')
        self.assertEqual(self.read()['freshness'], 'fresh')
        self.assertEqual(self.read()['input_revision'], 1)

    def test_schema_upgrade_creates_versioned_revision(self):
        self.build_first()
        with patch.object(policy, 'SCHEMA_VERSION', 'next-schema'):
            repo.schedule_versions()
            for _ in range(3):
                self.process()
            self.assertEqual(self.read()['revision']['schema_version'], 'next-schema')

    def test_background_worker_processes_api_request(self):
        self.refresh()
        stop, generated = threading.Event(), threading.Event()
        self.generator.callback = generated.set
        with patch('app.company_profile_worker.OpenAIProfileGenerator', return_value=self.generator):
            thread = threading.Thread(target=worker.worker, args=(stop,))
            thread.start()
            try:
                self.assertTrue(generated.wait(5))
            finally:
                stop.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.read()['freshness'], 'fresh')

    def test_relationships_without_metrics_are_effective_inputs(self):
        self.build_first()
        with repo.database() as db:
            account = self.add_account(db, self.company, 'meta_ads')
            ad = self.add_item(db, account, 'meta_ads', analyzed=False, ad=True)
            db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (ad, self.item))
            repo.invalidate(db, self.company, ['instagram'], 'relationship_changed')
        self.process()
        self.assertEqual(len(self.generator.calls), 2)
        self.assertEqual(self.generator.calls[-1]['performances'], [])
        self.assertEqual(self.generator.calls[-1]['relationships'], [
            {'ad_item_id': str(ad), 'video_item_id': str(self.item)}])

    def test_new_inputs_reset_exhausted_lease_attempts(self):
        self.refresh()
        for _ in range(policy.MAX_ATTEMPTS):
            job = repo.claim()
            with repo.database() as db:
                db.execute("UPDATE company_profile_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job['id'],))
        self.invalidate()
        job = repo.claim()
        self.assertIsNotNone(job)
        self.assertEqual(job['attempts'], 1)
        worker.process_job(job, self.adapter, self.generator)
        self.assertEqual(self.read()['freshness'], 'fresh')


class GeneratorContractTests(unittest.TestCase):
    def test_provider_output_limit_and_configuration(self):
        generator = OpenAIProfileGenerator()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch('app.company_profile_generator.OpenAI') as client:
            response = MagicMock(status='completed', output_text='{}')
            client.return_value.__enter__.return_value.responses.create.return_value = response
            self.assertEqual(generator.generate({})['topics'], [])
            args = client.return_value.__enter__.return_value.responses.create.call_args.kwargs
            self.assertEqual(args['max_output_tokens'], policy.MAX_OUTPUT_TOKENS)
            self.assertFalse(args['store'])
            self.assertEqual(client.call_args.kwargs['max_retries'], 0)
            response.status = 'incomplete'
            with self.assertRaises(InvalidProfile):
                generator.generate({})

    def test_unknown_refs_and_unmeasured_rankings_are_rejected(self):
        bundle = {'payload': {'scope': 'instagram', 'coverage': {}},
                  'manifest': {'references': {'item:a': {'kind': 'content', 'item_id': 'a'}}}}
        claim = {'text': 'Claim', 'evidence_refs': ['unknown'], 'comparison_basis': 'sample',
                 'evidence_kind': 'content', 'confidence': 'low'}
        with self.assertRaises(InvalidProfile):
            validate({'topics': [claim]}, bundle)
        claim['evidence_refs'] = ['item:a']
        with self.assertRaises(InvalidProfile):
            validate({'strong_themes': [claim]}, bundle)
        with self.assertRaises(InvalidProfile):
            validate({'user_preferences': [claim]}, bundle)

    def test_hard_limits_reject_before_call_and_before_persistence(self):
        generator = OpenAIProfileGenerator()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}), patch('app.company_profile_generator.OpenAI') as client:
            with self.assertRaises(InvalidProfile):
                generator.generate({'oversized': 'x' * policy.MAX_INPUT_BYTES})
            client.assert_not_called()
            client.return_value.__enter__.return_value.responses.create.return_value = MagicMock(
                status='completed', output_text='x' * (policy.MAX_OUTPUT_BYTES + 1))
            with self.assertRaises(InvalidProfile):
                generator.generate({})

    def test_measured_comparison_preserves_currency_and_null_semantics(self):
        from app.company_profile_generator import comparable
        refs = {
            'a': {'kind': 'measured_performance', 'item_id': 'a', 'known_metrics': ['view_count'],
                  'context': {'source': 'meta_ads', 'currency': 'EUR'}},
            'b': {'kind': 'measured_performance', 'item_id': 'b', 'known_metrics': ['view_count'],
                  'context': {'source': 'meta_ads', 'currency': 'USD'}},
        }
        self.assertFalse(comparable(['a', 'b'], refs))
        refs['b']['context']['currency'] = 'EUR'
        self.assertTrue(comparable(['a', 'b'], refs))
        refs['b']['known_metrics'] = []
        self.assertFalse(comparable(['a', 'b'], refs))


if __name__ == '__main__':
    unittest.main()
