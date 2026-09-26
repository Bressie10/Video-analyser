"""Regression probes found during the integrated V3 release audit."""
import os
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb

from app import company_profile_repository as profiles
from app import company_profile_worker as worker
from app import meta_library_discovery as discovery
from app import meta_library_repository as library
import test_company_profile_integration as fixtures
from test_persistent_ideas import RESULT


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CompanyProfileIntegrationTests('test_shared_ads_account_evidence_is_item_scoped')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.f = self.fixture.f
        self.f.db.execute("UPDATE meta_library_items SET external_id='100101' WHERE id=%s", (self.f.ad_a,))
        self.account = self.f.db.execute('SELECT * FROM meta_accounts WHERE id=%s', (self.f.ads,)).fetchone()

    def remove_creative(self, db=None):
        db = db or self.f.db
        with db.transaction():
            discovery.import_ad(db, {'run_id': self.f.run, 'connection_id': self.f.connection},
                                self.account, {'id': '100101', 'creative': {}}, None)

    def test_discovery_removal_suppresses_only_owner_profiles(self):
        self.fixture.drain()
        before_b = self.fixture.states(self.f.b)
        self.remove_creative()
        self.assertNotIn(self.f.creative, self.f.ids(self.f.a))
        for scope in ('facebook', 'meta_ads', 'shared'):
            response = self.fixture.client.get(self.fixture.url(self.f.a, scope))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['usable'])
            self.assertNotIn(str(self.f.creative), response.text)
        self.assertEqual(self.fixture.states(self.f.b), before_b)
        before_a = self.fixture.states(self.f.a)
        self.remove_creative()
        self.assertEqual(self.fixture.states(self.f.a), before_a)  # Repeated discovery is a no-op.
        self.fixture.drain()
        self.assertNotIn(str(self.f.creative), self.fixture.client.get(self.fixture.url(self.f.a)).text)

    def test_discovery_removal_fences_running_profile_worker(self):
        job_id = self.f.db.execute("""SELECT j.id FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
            WHERE p.company_id=%s AND p.scope='meta_ads'""", (self.f.a,)).fetchone()['id']
        self.f.db.execute("UPDATE company_profile_jobs SET available_at=now()+interval '1 hour' WHERE id<>%s", (job_id,))
        job = profiles.claim()
        self.fixture.generator.callback = self.remove_creative
        worker.process_job(job, self.fixture.adapter, self.fixture.generator)
        current = profiles.read(self.f.db, self.f.a, 'meta_ads')
        self.assertFalse(current['usable'])
        self.assertEqual(current['job']['state'], 'queued')

    def test_discovery_removal_and_invalidation_roll_back_together(self):
        self.fixture.drain()
        before = self.fixture.states(self.f.a)
        with patch('app.company_profile_repository.invalidate', side_effect=RuntimeError('failed invalidation')):
            with self.assertRaises(RuntimeError):
                self.remove_creative()
        self.assertIn(self.f.creative, self.f.ids(self.f.a))
        self.assertEqual(self.fixture.states(self.f.a), before)

    def test_discovery_respects_authorization_lock_through_persistence(self):
        with library.database() as db:
            db.execute('SELECT id FROM meta_connections WHERE id=%s FOR SHARE', (self.f.connection,))
            with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                other.execute("SET LOCAL lock_timeout='50ms'")
                self.remove_creative(other)

    def test_refresh_request_cannot_reference_another_profile_job(self):
        profile_id = profiles.profile(self.f.db, self.f.a, 'facebook')['id']
        for company, scope in ((self.f.a, 'instagram'), (self.f.b, 'facebook')):
            job = self.f.db.execute('''SELECT j.id FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
                WHERE p.company_id=%s AND p.scope=%s LIMIT 1''', (company, scope)).fetchone()['id']
            with self.subTest(company=company, scope=scope), self.assertRaises(psycopg.errors.ForeignKeyViolation):
                self.f.db.execute('''INSERT INTO company_profile_refresh_requests(profile_id,idempotency_key,job_id)
                    VALUES (%s,%s,%s)''', (profile_id, f'cross-profile-{company}-{scope}', job))

    def test_migration_010_preserves_valid_refreshes_and_rejects_bad_upgrade(self):
        # Reconstruct 009's constraints in this disposable schema, then verify
        # both a populated valid upgrade and atomic rejection of invalid data.
        path = Path(__file__).resolve().parents[1] / 'migrations/010_profile_refresh_integrity.sql'
        self.f.db.execute('ALTER TABLE company_profile_refresh_requests DROP CONSTRAINT company_profile_refresh_requests_profile_job_fk')
        self.f.db.execute('ALTER TABLE company_profile_jobs DROP CONSTRAINT company_profile_jobs_profile_key')
        self.f.db.execute('''ALTER TABLE company_profile_refresh_requests
            ADD CONSTRAINT company_profile_refresh_requests_job_id_fkey FOREIGN KEY(job_id) REFERENCES company_profile_jobs(id)''')
        valid = profiles.refresh(self.f.db, self.f.a, 'facebook', 'valid-upgrade')
        before = self.f.db.execute('SELECT * FROM company_profile_refresh_requests').fetchall()
        self.f.db.execute(path.read_text())
        self.assertEqual(self.f.db.execute('SELECT * FROM company_profile_refresh_requests').fetchall(), before)
        self.assertEqual(profiles.refresh(self.f.db, self.f.a, 'facebook', 'valid-upgrade')['job_id'], valid['job_id'])
        self.f.db.execute('ALTER TABLE company_profile_refresh_requests DROP CONSTRAINT company_profile_refresh_requests_profile_job_fk')
        self.f.db.execute('ALTER TABLE company_profile_jobs DROP CONSTRAINT company_profile_jobs_profile_key')
        self.f.db.execute('''ALTER TABLE company_profile_refresh_requests
            ADD CONSTRAINT company_profile_refresh_requests_job_id_fkey FOREIGN KEY(job_id) REFERENCES company_profile_jobs(id)''')
        profile_id = profiles.profile(self.f.db, self.f.a, 'facebook')['id']
        job = self.f.db.execute('''SELECT j.id FROM company_profile_jobs j JOIN company_profiles p ON p.id=j.profile_id
            WHERE p.company_id=%s LIMIT 1''', (self.f.b,)).fetchone()['id']
        self.f.db.execute('INSERT INTO company_profile_refresh_requests VALUES (%s,%s,%s,now())', (profile_id, 'invalid-upgrade', job))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.f.db.execute(path.read_text())
        self.f.db.execute('ROLLBACK')
        self.assertIsNone(self.f.db.execute("SELECT to_regclass('company_profile_jobs_profile_key') AS name").fetchone()['name'])

    def test_discovery_provider_resolution_precedes_revocation_lock(self):
        self.fixture.drain()
        before_b = self.fixture.states(self.f.b)
        before_a = self.fixture.states(self.f.a)
        class Provider:
            def get(inner, path, params):
                # The connection lock must not span a provider request.
                with library.database() as other:
                    other.execute("SET LOCAL lock_timeout='50ms'")
                    other.execute('SELECT id FROM meta_connections WHERE id=%s FOR UPDATE', (self.f.connection,))
                return {'attachments': {'data': [{'media_type': 'video', 'target': {'id': '200202'}}]}}
        with self.f.db.transaction():
            discovery.import_ad(self.f.db, {'run_id': self.f.run, 'connection_id': self.f.connection}, self.account,
                                {'id': '100101', 'creative': {'effective_object_story_id': '1_2'}}, Provider())
        # Replacement removes the previous edge and must suppress, not merely stale.
        self.assertTrue(self.fixture.states(self.f.a)['shared'][1])
        self.assertGreater(self.fixture.states(self.f.a)['shared'][0], before_a['shared'][0])
        self.assertEqual(self.fixture.states(self.f.b), before_b)

    def test_discovery_addition_stales_only_owner_without_suppressing(self):
        self.fixture.drain()
        before_b = self.fixture.states(self.f.b)
        self.f.db.execute("UPDATE meta_library_items SET external_id='200201' WHERE id=%s", (self.f.creative,))
        with self.f.db.transaction():
            discovery.import_ad(self.f.db, {'run_id': self.f.run, 'connection_id': self.f.connection}, self.account,
                {'id': '100101', 'creative': {'asset_feed_spec': {'videos': [{'video_id': '200201'}, {'video_id': '200202'}]}}}, None)
        current = profiles.read(self.f.db, self.f.a, 'shared')
        self.assertTrue(current['usable'])
        self.assertEqual(current['freshness'], 'stale')
        self.assertEqual(self.fixture.states(self.f.b), before_b)

    def test_discovery_removal_blocks_idea_using_revoked_profile_evidence(self):
        self.fixture.drain()
        self.f.db.execute('UPDATE meta_library_performance SET snapshot=%s',
            (Jsonb({'performance_source': 'facebook', 'performance_metrics': {'view_count': 1}}),))
        def revoke(*args, **kwargs):
            self.remove_creative()
            return RESULT
        with patch('app.idea_service.generate_idea', side_effect=revoke) as generated:
            response = self.fixture.client.post(f'/api/meta/companies/{self.f.a}/recommendations',
                json={'request_id': str(uuid4()), 'video_ids': [str(self.f.organic)]})
        generated.assert_called_once()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)
