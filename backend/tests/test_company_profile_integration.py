"""006/007 integration: real ownership/authentication, stubbed model/provider calls."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from app import company_ownership_repository as ownership
from app import company_profile_evidence as evidence
from app import company_profile_repository as profiles
from app import company_profile_types as policy
from app import company_profile_worker as worker
from app import meta
from app import meta_library_repository as library
from app.company_profile_company import (
    OwnershipCompanyAdapter, get_company_adapter, bind_company_adapter, CompanyLayerUnavailable,
)
from app.main import app
import test_company_ownership as ownership_tests
from test_company_profiles import FakeGenerator


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyProfileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = ownership_tests.CompanyOwnershipTests('test_two_companies_and_exclusive_organic_accounts')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        f = self.f
        env = patch.dict(os.environ, {'DATABASE_URL': f.url, 'COMPANY_PROFILE_WORKER_ENABLED': 'false',
                                     'META_WORKER_ENABLED': 'false'})
        env.start()
        self.addCleanup(env.stop)
        # Fail loudly if an integration test accidentally reaches a real provider.
        for target in ('app.company_profile_generator.OpenAI', 'app.meta.MetaClient'):
            guard = patch(target, side_effect=AssertionError('Real provider calls are forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        self.adapter = OwnershipCompanyAdapter()
        old = get_company_adapter()
        bind_company_adapter(self.adapter)
        self.addCleanup(bind_company_adapter, old)
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)
        session = 'integration-session'
        f.db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day')",
                     (library.token_hash(session), f.connection))
        self.client.cookies.set(meta.SESSION_COOKIE, session, path='/api')
        f.shared_setup()
        f.link(f.a, f.fb)
        f.link(f.a, f.ig)
        fb_b, ig_b = f.account('facebook', 'fb-b'), f.account('instagram', 'ig-b')
        f.link(f.b, fb_b)
        f.link(f.b, ig_b)
        self.b_facebook = f.item(fb_b, 'B FACEBOOK PRIVATE', 'video', 'facebook')
        self.b_instagram = f.item(ig_b, 'B INSTAGRAM PRIVATE', 'reel', 'instagram')
        self.items = {f.a: (f.organic, f.instagram), f.b: (self.b_facebook, self.b_instagram)}
        for company, ids in self.items.items():
            for identity in ids:
                video = f.db.execute('''INSERT INTO videos(duration_seconds,container,file_size_bytes,
                    meta_connection_id,transcript_text) VALUES (5,'mp4',10,%s,%s) RETURNING id''',
                    (f.connection, 'A CONTENT' if company == f.a else 'B CONTENT')).fetchone()['id']
                f.db.execute("""UPDATE meta_library_items SET video_id=%s,analysis_state='completed',
                    analysis_version=1 WHERE id=%s""", (video, identity))
        f.db.execute("""UPDATE meta_library_items SET analysis_state='completed',analysis_version=1,
            label='b-secret',analysis_error='b-secret',metrics_error='b-secret' WHERE id=%s""", (f.creative,))
        self.generator = FakeGenerator()

    def url(self, company, scope='shared'):
        return f'/api/companies/{company}/profiles/{scope}'

    def states(self, company):
        return {r['scope']: (r['input_revision'], r['suppressed'], r['current_revision_id']) for r in
                self.f.db.execute('SELECT * FROM company_profiles WHERE company_id=%s', (company,)).fetchall()}

    def assert_invalidated(self, before, company):
        after = self.states(company)
        self.assertEqual(set(after), set(policy.SCOPES))
        for scope in policy.SCOPES:
            self.assertEqual(after[scope][0], before[scope][0] + 1, scope)
            self.assertTrue(after[scope][1], scope)
            self.assertEqual(after[scope][2], before[scope][2], scope)

    def drain(self):
        captured = []
        for _ in range(30):
            job = profiles.claim()
            if job is None:
                return captured
            before = len(self.generator.calls)
            worker.process_job(job, self.adapter, self.generator)
            state = self.f.db.execute('SELECT state FROM company_profile_jobs WHERE id=%s', (job['id'],)).fetchone()['state']
            self.assertEqual(state, 'completed')
            if len(self.generator.calls) > before:
                captured.append((job['company_id'], self.generator.calls[-1]))
        self.fail('Profile queue did not drain')

    def test_shared_ads_account_evidence_is_item_scoped(self):
        f = self.f
        for company, own, other in ((f.a, f.ad_a, f.ad_b), (f.b, f.ad_b, f.ad_a)):
            with f.db.transaction():
                access = self.adapter.evidence_access(f.db, company)
                payload = evidence.platform(f.db, company, 'meta_ads', access)
            self.assertEqual({m['item_id'] for m in payload['performances']}, {own})
            self.assertEqual({r['ad_item_id'] for r in payload['relationships']}, {own})
            self.assertEqual([i['analysis']['id'] for i in payload['items']], [f.video])
            self.assertNotEqual(f.creative, f.video)
            self.assertNotIn(str(other), evidence.encoded(payload))
            self.assertNotIn(str(f.unassigned), evidence.encoded(payload))
            self.assertTrue(all(item['label'] is None for item in payload['items']))

    def test_platform_and_shared_model_inputs_and_cached_manifests_are_isolated(self):
        f = self.f
        calls = self.drain()
        self.assertEqual(len(calls), 8)
        for company, payload in calls:
            other = f.b if company == f.a else f.a
            forbidden = [f.ad_b if company == f.a else f.ad_a, f.unassigned, *self.items[other]]
            text = evidence.encoded(payload)
            for identity in forbidden:
                self.assertNotIn(str(identity), text)
            for marker in ('b-secret', 'B CONTENT') if company == f.a else ('a-secret', 'A CONTENT'):
                self.assertNotIn(marker, text)
        for company in (f.a, f.b):
            other = f.b if company == f.a else f.a
            forbidden = [f.ad_b if company == f.a else f.ad_a, f.unassigned, *self.items[other]]
            for scope in policy.SCOPES:
                response = self.client.get(self.url(company, scope))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['freshness'], 'fresh')
                for identity in forbidden:
                    self.assertNotIn(str(identity), response.text)

    def test_assign_unassign_reassign_invalidate_only_affected_companies(self):
        f = self.f
        self.drain()
        before_a, before_b = self.states(f.a), self.states(f.b)
        f.assign(f.a, f.unassigned)
        self.assert_invalidated(before_a, f.a)
        self.assertEqual(self.states(f.b), before_b)
        self.assertFalse(self.client.get(self.url(f.a)).json()['usable'])
        before_a = self.states(f.a)
        ownership.unassign_ad(f.db, f.connection, f.a, f.unassigned)
        self.assert_invalidated(before_a, f.a)
        self.assertEqual(self.states(f.b), before_b)
        before_a = self.states(f.a)
        ownership.reassign_ad(f.db, f.connection, f.a, f.b, f.ad_a)
        self.assert_invalidated(before_a, f.a)
        self.assert_invalidated(before_b, f.b)
        self.drain()
        for company, expected in ((f.a, set()), (f.b, {f.ad_a, f.ad_b})):
            payload = evidence.platform(f.db, company, 'meta_ads', self.adapter.evidence_access(f.db, company))
            self.assertEqual({m['item_id'] for m in payload['performances']}, expected)

    def test_account_link_unlink_and_transfer_hooks(self):
        f = self.f
        before_a, before_b = self.states(f.a), self.states(f.b)
        account = f.account('instagram', 'new-account')
        f.link(f.a, account)
        self.assert_invalidated(before_a, f.a)
        self.assertEqual(self.states(f.b), before_b)
        before_a = self.states(f.a)
        ownership.unlink_account(f.db, f.connection, f.a, account)
        self.assert_invalidated(before_a, f.a)
        self.assertEqual(self.states(f.b), before_b)
        before_a = self.states(f.a)
        ownership.reassign_organic_account(f.db, f.connection, f.a, f.b, f.ig)
        self.assert_invalidated(before_a, f.a)
        self.assert_invalidated(before_b, f.b)

    def test_noops_and_failed_changes_do_not_invalidate(self):
        f = self.f
        self.drain()
        before_a, before_b = self.states(f.a), self.states(f.b)
        f.link(f.a, f.ads)
        f.assign(f.a, f.ad_a)
        ownership.unassign_ad(f.db, f.connection, f.a, f.ad_b)
        empty_account = f.account('instagram', 'not-linked')
        ownership.unlink_account(f.db, f.connection, f.a, empty_account)
        ownership.reassign_ad(f.db, f.connection, f.a, f.a, f.ad_a)
        ownership.reassign_organic_account(f.db, f.connection, f.a, f.a, f.ig)
        ownership.set_company_archived(f.db, f.connection, f.a, archived=False)
        with self.assertRaises(ownership.OwnershipConflict):
            ownership.unlink_account(f.db, f.connection, f.a, f.ads)
        with self.assertRaises(ownership.OwnershipConflict):
            f.assign(f.a, f.ad_b)
        self.assertEqual(self.states(f.a), before_a)
        self.assertEqual(self.states(f.b), before_b)

    def test_rollback_and_hook_failure_preserve_ownership_and_cache(self):
        f = self.f
        self.drain()
        before = self.states(f.a)
        with self.assertRaises(RuntimeError), f.db.transaction():
            ownership.unassign_ad(f.db, f.connection, f.a, f.ad_a)
            raise RuntimeError('Roll back caller transaction')
        with patch('app.company_profile_repository.invalidate', side_effect=RuntimeError('Hook failed')):
            with self.assertRaises(RuntimeError):
                ownership.unassign_ad(f.db, f.connection, f.a, f.ad_a)
        self.assertEqual(self.states(f.a), before)
        self.assertIn(f.ad_a, f.ids(f.a))
        self.assertTrue(self.client.get(self.url(f.a)).json()['usable'])

    def test_archive_blocks_reads_refresh_and_workers_restore_resumes(self):
        f = self.f
        self.drain()
        before_a, before_b = self.states(f.a), self.states(f.b)
        ownership.set_company_archived(f.db, f.connection, f.a)
        self.assert_invalidated(before_a, f.a)
        self.assertEqual(self.states(f.b), before_b)
        for scope in policy.SCOPES:
            response = self.client.get(self.url(f.a, scope))
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('document', response.json())
            self.assertEqual(self.client.post(self.url(f.a, scope) + '/refresh',
                headers={'Idempotency-Key': str(uuid4())}).status_code, 404)
        self.assertEqual(self.client.get(f'/api/companies/{f.a}/profiles').status_code, 404)
        with self.assertRaises(CompanyLayerUnavailable):
            self.adapter.evidence_access(f.db, f.a)
        self.assertIsNone(profiles.claim())
        before_a = self.states(f.a)
        ownership.set_company_archived(f.db, f.connection, f.a, archived=False)
        self.assert_invalidated(before_a, f.a)
        self.assertFalse(self.client.get(self.url(f.a)).json()['usable'])
        self.drain()
        self.assertTrue(self.client.get(self.url(f.a)).json()['usable'])
        self.assertEqual(f.ids(f.a), {f.ad_a, f.creative, f.organic, f.instagram})

    def test_change_during_generation_cannot_publish_old_evidence(self):
        f = self.f
        # Select A's paid job rather than relying on queue ordering between companies.
        job = f.db.execute("""SELECT j.id FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
            WHERE p.company_id=%s AND p.scope='meta_ads'""", (f.a,)).fetchone()
        f.db.execute("UPDATE company_profile_jobs SET available_at=now()+interval '1 hour' WHERE id<>%s", (job['id'],))
        claimed = profiles.claim()
        self.generator.callback = lambda: ownership.reassign_ad(f.db, f.connection, f.a, f.b, f.ad_a)
        worker.process_job(claimed, self.adapter, self.generator)
        current = profiles.read(f.db, f.a, 'meta_ads')
        self.assertFalse(current['usable'])
        self.assertEqual(current['job']['state'], 'queued')
        self.assertEqual(f.db.execute('SELECT count(*) AS n FROM company_profile_revisions').fetchone()['n'], 0)

    def test_authenticated_connection_boundary_and_disconnect(self):
        f = self.f
        self.assertEqual(self.client.get(self.url(f.a)).status_code, 200)
        self.assertEqual(self.client.get(self.url(f.b)).status_code, 200)
        self.assertEqual(self.client.get(self.url(f.foreign_company)).status_code, 404)
        self.assertEqual(self.client.post(self.url(f.foreign_company) + '/refresh',
            headers={'Idempotency-Key': 'foreign'}).status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.url(f.a)).status_code, 401)
        self.client.cookies.set(meta.SESSION_COOKIE, 'forged', path='/api')
        self.assertEqual(self.client.get(self.url(f.a)).status_code, 401)
        self.client.cookies.set(meta.SESSION_COOKIE, 'integration-session', path='/api')
        library.disconnect(f.connection)
        self.assertEqual(self.client.get(self.url(f.a)).status_code, 401)
        self.assertEqual(len(ownership.list_companies(f.db, f.connection)), 2)

    def test_concurrent_refresh_and_transfer_have_consistent_lock_order(self):
        f = self.f
        barrier = threading.Barrier(2)
        def refresh():
            with profiles.database() as db:
                db.execute("SET lock_timeout='3s'")
                barrier.wait(timeout=5)
                profiles.refresh(db, f.a, 'instagram', 'concurrent')
        def transfer():
            with profiles.database() as db:
                db.execute("SET lock_timeout='3s'")
                barrier.wait(timeout=5)
                ownership.reassign_ad(db, f.connection, f.a, f.b, f.ad_a)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(refresh), pool.submit(transfer)]
            for future in futures:
                future.result(timeout=10)
        self.assertNotIn(f.ad_a, f.ids(f.a))
        self.assertIn(f.ad_a, f.ids(f.b))

    def test_missing_profile_schema_rolls_back_access_change(self):
        f = self.f
        before = f.db.execute('SELECT * FROM company_ad_assignments WHERE ad_item_id=%s', (f.ad_a,)).fetchone()
        with self.assertRaises(psycopg.errors.UndefinedTable), f.db.transaction():
            f.db.execute('ALTER TABLE company_profiles RENAME TO unavailable_profiles')
            ownership.unassign_ad(f.db, f.connection, f.a, f.ad_a)
        self.assertEqual(f.db.execute('SELECT * FROM company_ad_assignments WHERE ad_item_id=%s', (f.ad_a,)).fetchone(), before)

    def test_legacy_cross_connection_edges_and_unowned_video_are_excluded(self):
        f = self.f
        foreign_asset = f.item(f.foreign_ads, 'FOREIGN ASSET', 'video', 'facebook', f.foreign_connection)
        f.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s),(%s,%s)',
                     (f.ad_a, foreign_asset, f.foreign_ad, f.creative))
        payload = evidence.platform(f.db, f.a, 'meta_ads', self.adapter.evidence_access(f.db, f.a))
        self.assertNotIn(str(foreign_asset), evidence.encoded(payload))
        self.assertNotIn(str(f.foreign_ad), evidence.encoded(payload))
        self.assertNotIn('987654', evidence.encoded(payload))  # Legacy video snapshot never enters analysis.
