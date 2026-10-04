"""V8 usage decisions against fresh PostgreSQL and signed company APIs."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth_repository, billing_repository as billing, entitlements
from app.auth import get_token_verifier
from app.main import app
from auth_fixtures import USER_ID, OTHER_USER_ID
import test_auth_database


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class EntitlementTests(unittest.TestCase):
    def setUp(self):
        self.f = test_auth_database.AuthDatabaseTests('test_fresh_schema_company_creation_and_membership')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.company = self.f.create()
        app.dependency_overrides[get_token_verifier] = lambda: self.f.auth.verifier
        self.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)

    def call(self, method, path, *, user=USER_ID, **kwargs):
        headers = kwargs.pop('headers', {})
        if user:
            headers['Authorization'] = 'Bearer ' + self.f.auth.token(sub=str(user))
        return self.client.request(method, path, headers=headers, **kwargs)

    def reserve(self, company, kind, identity=None):
        identity = identity or uuid4()
        return entitlements.reserve_usage(self.f.db, company, kind,
            f'{kind}:{identity}:reserve', 'test_operation', identity)

    def make_pro(self, company):
        company = UUID(str(company))
        billing.initialize(self.f.db, company)
        self.f.db.execute('''UPDATE company_billing SET plan_code='pro',
            stripe_customer_id=%s,stripe_subscription_id=%s,
            subscription_status='active' WHERE company_id=%s''',
            ('cus_' + company.hex, 'sub_' + company.hex, company))

    def test_free_workspace_creation_owner_membership_and_rollback(self):
        first = self.call('POST', '/api/companies', user=OTHER_USER_ID,
                          json={'name': 'First'})
        self.assertEqual(first.status_code, 201, first.text)
        before = self.f.db.execute('SELECT count(*) AS n FROM companies').fetchone()['n']
        blocked = self.call('POST', '/api/companies', user=OTHER_USER_ID,
                            json={'name': 'Second'})
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.json()['detail']['code'], 'free_workspace_limit_reached')
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM companies').fetchone()['n'], before)
        self.assertEqual(self.call('GET', f'/api/companies/{first.json()["company_id"]}',
                                   user=OTHER_USER_ID).status_code, 200)
        self.make_pro(first.json()['company_id'])
        self.assertEqual(self.call('POST', '/api/companies', user=OTHER_USER_ID,
                                   json={'name': 'Second'}).status_code, 201)
        self.assertEqual(self.call('POST', '/api/companies', user=OTHER_USER_ID,
                                   json={'name': 'Third'}).status_code, 402)

    def test_membership_does_not_count_and_legacy_owners_remain_visible(self):
        auth_repository.ensure_profile(self.f.db, OTHER_USER_ID)
        self.f.db.execute("INSERT INTO company_memberships VALUES (%s,%s,'member')",
                          (self.company, OTHER_USER_ID))
        self.assertEqual(self.call('POST', '/api/companies', user=OTHER_USER_ID,
                                   json={'name': 'Own Free'}).status_code, 201)
        self.f.create(OTHER_USER_ID, 'Legacy Free')
        self.assertEqual(len(self.call('GET', '/api/companies', user=OTHER_USER_ID)
                             .json()['companies']), 3)
        self.assertEqual(self.call('POST', '/api/companies', user=OTHER_USER_ID,
                                   json={'name': 'Blocked'}).status_code, 402)

    def test_concurrent_free_workspace_creation_has_one_winner(self):
        def create(index):
            return self.call('POST', '/api/companies', user=OTHER_USER_ID,
                             json={'name': str(index)}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(create, range(2))), [201, 402])
        self.assertEqual(self.f.db.execute('''SELECT count(*) AS n FROM company_memberships
            WHERE user_id=%s AND role='owner' ''', (OTHER_USER_ID,)).fetchone()['n'], 1)

    def test_free_and_pro_usage_limits_and_per_company_scope(self):
        for index, (kind, free_limit, pro_limit) in enumerate((
                ('analysis', 3, 50), ('idea_generation', 5, 150))):
            company = self.company if index == 0 else self.f.create()
            other = self.f.create(OTHER_USER_ID)
            for _ in range(free_limit):
                self.reserve(company, kind)
            with self.assertRaises(HTTPException) as error:
                self.reserve(company, kind)
            self.assertEqual(error.exception.status_code, 402)
            self.reserve(other, kind)
            self.make_pro(company)
            for _ in range(pro_limit - free_limit):
                self.reserve(company, kind)
            with self.assertRaises(HTTPException):
                self.reserve(company, kind)

    def test_idempotent_reservation_refund_and_period_roll(self):
        operation = uuid4()
        reserve_key = f'analysis:{operation}:reserve'
        refund_key = f'analysis:{operation}:refund'
        self.reserve(self.company, 'analysis', operation)
        self.reserve(self.company, 'analysis', operation)
        for _ in range(2):
            state = entitlements.refund_usage(self.f.db, self.company, 'analysis',
                reserve_key, refund_key, 'test_operation', operation)
        self.assertEqual(state['usage']['analyses'], 0)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM company_usage_ledger'
            ).fetchone()['n'], 2)
        self.f.db.execute('''UPDATE company_billing SET current_period_start=now()-interval '40 days',
            current_period_end=now()-interval '1 day' WHERE company_id=%s''', (self.company,))
        self.assertEqual(self.reserve(self.company, 'analysis')['usage']['analyses'], 1)

    def test_concurrent_final_usage_slots(self):
        for kind, limit, field in (('analysis', 3, 'analyses'),
                                   ('idea_generation', 5, 'idea_generations')):
            for _ in range(limit - 1):
                self.reserve(self.company, kind)
            def reserve(index):
                with psycopg.connect(self.f.url, row_factory=dict_row) as db:
                    try:
                        entitlements.reserve_usage(db, self.company, kind,
                            f'{kind}:race:{index}', 'test_operation', str(index))
                        return 200
                    except HTTPException as error:
                        return error.status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(reserve, range(2))), [200, 402])
            row = billing.initialize(self.f.db, self.company)
            self.assertEqual(billing.usage(self.f.db, row)[field], limit)

    def test_past_due_grace_and_expiry_share_effective_plan(self):
        self.make_pro(self.company)
        self.f.db.execute('''UPDATE company_billing SET subscription_status='past_due',
            current_period_start=now()-interval '31 days',
            current_period_end=now()-interval '1 hour',
            grace_until=now()+interval '1 day' WHERE company_id=%s''', (self.company,))
        for _ in range(4):
            state = self.reserve(self.company, 'analysis')
        self.assertEqual(state['effective_plan'], 'pro')
        self.assertEqual(state['usage']['analyses'], 4)
        expired = self.f.create()
        self.make_pro(expired)
        self.f.db.execute('''UPDATE company_billing SET subscription_status='past_due',
            current_period_start=now()-interval '31 days',
            current_period_end=now()-interval '1 day',
            grace_until=now()-interval '1 hour' WHERE company_id=%s''', (expired,))
        for _ in range(3):
            state = self.reserve(expired, 'analysis')
        self.assertEqual(state['effective_plan'], 'free')
        with self.assertRaises(HTTPException):
            self.reserve(expired, 'analysis')

    def test_authorization_precedes_billing(self):
        self.assertEqual(self.call('POST', '/api/companies', user=None,
                                   json={'name': 'Unauthenticated'}).status_code, 401)
        self.assertEqual(self.call('GET', f'/api/companies/{self.company}/billing',
                                   user=OTHER_USER_ID).status_code, 403)
