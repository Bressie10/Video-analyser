"""Real 001-008 ownership/profile/idea flow; only model calls are stubbed."""
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app import company_ownership_repository as ownership
from app import meta_library_repository as library
from app import billing_repository as billing
from app.idea_generation import InvalidGeneration
import test_company_profile_integration as profile_tests
from test_persistent_ideas import RESULT
from company_auth_fixtures import grant, OTHER_USER_ID


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class IdeaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = profile_tests.CompanyProfileIntegrationTests('test_shared_ads_account_evidence_is_item_scoped')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.f = self.fixture.f
        self.client = self.fixture.client
        self.fixture.drain()
        stub = patch('app.idea_service.generate_idea', return_value=RESULT)
        self.model = stub.start()
        self.addCleanup(stub.stop)
        self.f.db.execute('UPDATE meta_library_performance SET snapshot=%s',
            (Jsonb({'performance_source': 'meta_ads', 'performance_metrics': {'view_count': 42}}),))

    def post(self, company=None, ids=None, body=None):
        return self.client.post(f'/api/meta/companies/{company or self.f.a}/recommendations',
            json=body or {'request_id': str(uuid4()), 'target_platforms': ['facebook'], 'video_ids': list(map(str, ids or [self.f.creative]))})

    def generate(self, **kwargs):
        response = self.post(**kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_v8_free_idea_quota_and_replay(self):
        first_body = {'request_id': str(uuid4()), 'target_platforms': ['facebook'],
                      'video_ids': [str(self.f.creative)]}
        saved = self.generate(body=first_body)
        for _ in range(4):
            self.generate()
        self.assertEqual(self.generate(body=first_body)['id'], saved['id'])
        blocked = self.post()
        self.assertEqual(blocked.status_code, 402, blocked.text)
        self.assertEqual(blocked.json()['detail']['code'], 'idea_generation_limit_reached')
        with library.database() as db:
            row = billing.initialize(db, self.f.a)
            self.assertEqual(billing.usage(db, row)['idea_generations'], 5)
        self.assertEqual(self.model.call_count, 5)

    def test_v8_model_failure_refunds_then_same_request_can_retry(self):
        body = {'request_id': str(uuid4()), 'target_platforms': ['facebook'],
                'video_ids': [str(self.f.creative)]}
        self.model.side_effect = InvalidGeneration('invalid model payload')
        self.assertEqual(self.post(body=body).status_code, 502)
        with library.database() as db:
            row = billing.initialize(db, self.f.a)
            self.assertEqual(billing.usage(db, row)['idea_generations'], 0)
        self.model.side_effect = None
        self.model.return_value = RESULT
        saved = self.generate(body=body)
        self.assertEqual(self.generate(body=body)['id'], saved['id'])
        with library.database() as db:
            row = billing.initialize(db, self.f.a)
            self.assertEqual(billing.usage(db, row)['idea_generations'], 1)
            self.assertEqual(db.execute('SELECT count(*) AS n FROM ideas WHERE company_id=%s',
                                        (self.f.a,)).fetchone()['n'], 1)

    def test_v8_member_consumes_company_allowance_without_cross_company_access(self):
        grant(self.f.db, [self.f.a], user_id=OTHER_USER_ID, role='member')
        self.client.headers['Authorization'] = 'Bearer ' + self.fixture.auth.token(sub=str(OTHER_USER_ID))
        self.generate()
        self.assertEqual(self.post(company=self.f.b).status_code, 403)
        with library.database() as db:
            row = billing.initialize(db, self.f.a)
            self.assertEqual(billing.usage(db, row)['idea_generations'], 1)
            other = billing.initialize(db, self.f.b)
            self.assertEqual(billing.usage(db, other)['idea_generations'], 0)

    def test_real_adapter_shared_creative_and_profile_revisions(self):
        for company, own, forbidden in ((self.f.a, self.f.ad_a, self.f.ad_b),
                                        (self.f.b, self.f.ad_b, self.f.ad_a)):
            saved = self.generate(company=company)
            payload = self.model.call_args.args[0]
            self.assertEqual({p['library_item_id'] for p in payload['performance_snapshots']}, {str(own)})
            for identity in (forbidden, self.f.unassigned, self.f.foreign_ad):
                self.assertNotIn(str(identity), json.dumps(payload))
            profile = self.f.db.execute("SELECT current_revision_id FROM company_profiles WHERE company_id=%s AND scope='shared'", (company,)).fetchone()
            self.assertEqual(saved['profile_revision_id'], str(profile['current_revision_id']))
            response = self.client.get(f"/api/meta/companies/{company}/ideas/{saved['id']}/evidence")
            self.assertEqual(response.json(), payload)
            self.assertEqual(set(payload['company_profile']['revision_ids']), {'shared','facebook','instagram','meta_ads'})
            self.assertNotIn('987654', json.dumps(payload))

    def test_foreign_company_and_unowned_sources_denied(self):
        for company, ids in ((self.f.foreign_company, [self.f.creative]),
                             (self.f.a, [self.fixture.b_facebook]),
                             (self.f.a, [self.f.ad_b]), (self.f.a, [self.f.unassigned])):
            self.assertEqual(self.post(company, ids).status_code, 403 if company == self.f.foreign_company else 404)
        self.model.assert_not_called()

    def test_reassignment_during_generation_rejects_persistence(self):
        def revoke(*args, **kwargs):
            ownership.reassign_ad(self.f.db, self.f.connection, self.f.a, self.f.b, self.f.ad_a)
            return RESULT
        self.model.side_effect = revoke
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)

    def test_profile_evidence_removed_outside_selection_rejects_persistence(self):
        def revoke(*args, **kwargs):
            ownership.unlink_account(self.f.db, self.f.connection, self.f.a, self.f.ig)
            return RESULT
        self.model.side_effect = revoke
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)

    def test_history_is_company_scoped_and_replay_survives_unlink(self):
        body = {'request_id': str(uuid4()), 'target_platforms': ['facebook'], 'video_ids': [str(self.f.creative)]}
        saved = self.generate(body=body)
        ownership.unassign_ad(self.f.db, self.f.connection, self.f.a, self.f.ad_a)
        self.assertEqual(self.generate(body=body)['id'], saved['id'])
        self.assertEqual(self.model.call_count, 1)
        for suffix in ('', '/evidence'):
            self.assertEqual(self.client.get(f"/api/meta/companies/{self.f.b}/ideas/{saved['id']}"+suffix).status_code, 404)

    def test_final_persistence_locks_ownership_and_membership(self):
        from app import idea_repository
        original = idea_repository.persist
        def persist(db, *args, **kwargs):
            for mutate in (
                lambda other: ownership.reassign_ad(other, self.f.connection, self.f.a, self.f.b, self.f.ad_a),
                lambda other: other.execute('DELETE FROM company_memberships'),
            ):
                with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                    other.execute("SET LOCAL lock_timeout='50ms'")
                    mutate(other)
            return original(db, *args, **kwargs)
        with patch('app.idea_service.ideas.persist', side_effect=persist):
            self.generate()

    def test_membership_revocation_during_model_call(self):
        def revoke(*args, **kwargs):
            self.f.db.execute('DELETE FROM company_memberships')
            return RESULT
        self.model.side_effect = revoke
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)

    def test_archive_during_model_call(self):
        def archive(*args, **kwargs):
            ownership.set_company_archived(self.f.db, self.f.connection, self.f.a)
            return RESULT
        self.model.side_effect = archive
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)

    def test_suppressed_profile_is_omitted_and_saved_evidence_stays_frozen(self):
        saved = self.generate()
        endpoint = f"/api/meta/companies/{self.f.a}/ideas/{saved['id']}/evidence"
        before = self.client.get(endpoint).json()
        ownership.unlink_account(self.f.db, self.f.connection, self.f.a, self.f.ig)
        second = self.generate()
        self.assertIsNone(second['profile_revision_id'])
        self.assertIsNone(self.model.call_args.args[0]['company_profile'])
        self.fixture.drain()
        self.assertEqual(self.client.get(endpoint).json(), before)

    def test_cross_connection_analysis_fk_is_denied(self):
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.f.db.execute('UPDATE videos SET meta_connection_id=%s WHERE id=%s',
                              (self.f.foreign_connection, self.f.video))
        self.model.assert_not_called()

    def test_content_access_does_not_grant_organic_metrics(self):
        # A owns the organic publication, B can use its content through B's ad.
        self.f.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.f.ad_b, self.f.organic))
        self.generate(company=self.f.b, ids=[self.f.organic])
        supplied = self.model.call_args.args[0]['performance_snapshots']
        self.assertEqual([row['library_item_id'] for row in supplied], [str(self.f.ad_b)])

    def test_metric_revocation_is_checked_even_when_content_stays_accessible(self):
        self.f.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.f.ad_a, self.f.organic))
        def transfer(*args, **kwargs):
            ownership.reassign_organic_account(self.f.db, self.f.connection, self.f.a, self.f.b, self.f.fb)
            self.assertIn(self.f.organic, self.f.ids(self.f.a))
            return RESULT
        self.model.side_effect = transfer
        self.assertEqual(self.post(ids=[self.f.organic]).status_code, 404)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 0)

    def test_profile_publication_and_suppression_are_locked_through_insert(self):
        from app import idea_repository, company_profile_repository
        original = idea_repository.persist
        def persist(db, *args, **kwargs):
            with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                other.execute("SET LOCAL lock_timeout='50ms'")
                company_profile_repository.invalidate(other, self.f.a, ['shared'], 'evidence_removed')
            return original(db, *args, **kwargs)
        with patch('app.idea_service.ideas.persist', side_effect=persist):
            self.generate()
