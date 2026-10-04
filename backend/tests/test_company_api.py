"""V4 API with real sessions, ownership and migrations 001-010."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import company_ownership_repository as repo
from app import meta, meta_library_repository as library
from app import billing_repository as billing
from app import meta_library_worker as worker
from app.main import app
from company_auth_fixtures import sign_in, grant
import test_company_ownership as ownership_tests


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyAPITests(unittest.TestCase):
    def setUp(self):
        self.f = ownership_tests.CompanyOwnershipTests('test_two_companies_and_exclusive_organic_accounts')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        env = patch.dict(os.environ, {'DATABASE_URL': self.f.url,
                                     'COMPANY_PROFILE_WORKER_ENABLED': 'false', 'META_WORKER_ENABLED': 'false',
                                     'META_TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode()})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)
        self.auth = sign_in(self, self.client)
        grant(self.f.db, [self.f.a, self.f.b], connection=self.f.connection)
        # These V4 management tests exercise multiple workspaces/accounts. Give
        # their existing fixture companies Pro access under the V8 contract.
        for company in (self.f.a, self.f.b):
            billing.initialize(self.f.db, company)
            self.f.db.execute('''UPDATE company_billing SET plan_code='pro',
                stripe_customer_id=%s,stripe_subscription_id=%s,
                subscription_status='active' WHERE company_id=%s''',
                ('cus_' + company.hex, 'sub_' + company.hex, company))
        self.f.db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day')",
                          (library.token_hash('company-api-session'), self.f.connection))
        self.client.cookies.set(meta.SESSION_COOKIE, 'company-api-session', path='/api')
        self.base = f'/api/companies/{self.f.a}'

    def request(self, method, path, status=200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        self.assertIn('no-store', response.headers['cache-control'])
        return response.json()

    def account(self, account, company=None):
        return f'/api/companies/{company or self.f.a}/accounts/{account}'

    def ad(self, ad, company=None):
        return f'/api/companies/{company or self.f.a}/ads/{ad}'

    def test_name_only_lifecycle(self):
        created = self.request('POST', '/api/companies', 201, json={'name': '  New company  '})
        self.assertEqual(created, {'company_id': created['company_id'], 'name': 'New company',
                                   'archived': False, 'accounts': [], 'role': 'owner'})
        path = '/api/companies/' + created['company_id']
        self.assertIn(created, self.request('GET', '/api/companies')['companies'])
        self.assertEqual(self.request('PATCH', path, json={'name': 'Renamed'})['name'], 'Renamed')
        self.assertTrue(self.request('POST', path + '/archive')['archived'])
        self.assertNotIn(created['company_id'], [r['company_id'] for r in self.request('GET', '/api/companies')['companies']])
        self.assertIn(created['company_id'], [r['company_id'] for r in self.request('GET', '/api/companies?include_archived=true')['companies']])
        self.assertTrue(self.request('GET', path)['archived'])
        self.request('PATCH', path, 403, json={'name': 'Cannot rename'})
        self.assertFalse(self.request('POST', path + '/restore')['archived'])
        self.request('PATCH', path, json={'name': 'Restored'})
        for body in ({'name': ''}, {'name': '  '}, {'name': 'x' * 201}, {'name': 'X', 'connection_id': str(self.f.foreign_connection)}):
            self.assertEqual(self.client.post('/api/companies', json=body).status_code, 422)

    def test_organic_exclusive_ownership_and_archived_owner(self):
        for account in (self.f.fb, self.f.ig):
            self.request('PUT', self.account(account))
            self.request('PUT', self.account(account))
            self.request('PUT', self.account(account, self.f.b), 409)
            self.request('PUT', self.account(account, self.f.foreign_company), 403)
        accounts = self.request('GET', '/api/meta/accounts')['accounts']
        fb = next(r for r in accounts if r['account_id'] == str(self.f.fb))
        self.assertEqual(fb['organic_owner'], {'company_id': str(self.f.a), 'name': 'A', 'archived': False})
        self.request('POST', self.base + '/archive')
        fb = next(r for r in self.request('GET', '/api/meta/accounts')['accounts'] if r['account_id'] == str(self.f.fb))
        self.assertTrue(fb['organic_owner']['archived'])
        self.request('PUT', self.account(self.f.fb, self.f.b), 409)
        self.request('POST', self.base + '/restore')
        for account in (self.f.fb, self.f.ig):
            self.request('DELETE', self.account(account))
            self.request('PUT', self.account(account, self.f.b))

    def test_shared_ads_assignment_unlink_and_atomic_reassignment(self):
        picker = self.account(self.f.ads) + '/ads'
        self.request('GET', picker, 404)
        self.request('PUT', self.account(self.f.ads))
        self.assertEqual(self.f.ids(self.f.a), set())
        self.assertEqual(len(self.request('GET', picker)['ads']), 3)
        self.request('PUT', self.ad(self.f.ad_a))
        self.request('PUT', self.ad(self.f.ad_a))
        self.request('DELETE', self.account(self.f.ads), 409)
        self.request('POST', self.ad(self.f.ad_a) + '/reassign', 409, json={'target_company_id': str(self.f.b)})
        self.assertIn(self.f.ad_a, self.f.ids(self.f.a))
        self.request('PUT', self.account(self.f.ads, self.f.b))
        self.request('PUT', self.ad(self.f.ad_a, self.f.b), 409)
        self.request('DELETE', self.ad(self.f.ad_a, self.f.b))
        self.assertIn(self.f.ad_a, self.f.ids(self.f.a))
        self.request('POST', self.ad(self.f.ad_a) + '/reassign', json={'target_company_id': str(self.f.b)})
        self.assertNotIn(self.f.ad_a, self.f.ids(self.f.a))
        self.assertIn(self.f.ad_a, self.f.ids(self.f.b))
        self.request('DELETE', self.account(self.f.ads))
        self.request('DELETE', self.account(self.f.ads, self.f.b), 409)
        self.request('DELETE', self.ad(self.f.ad_a, self.f.b))
        self.request('DELETE', self.account(self.f.ads, self.f.b))
        self.assertEqual(self.f.ids(self.f.b), set())

    def test_shared_creative_and_picker_do_not_leak_sibling_metadata(self):
        self.f.shared_setup()
        self.f.db.execute("UPDATE meta_library_items SET label='SIBLING PRIVATE',analysis_error='SIBLING PRIVATE' WHERE id=%s", (self.f.creative,))
        for company, own, other in ((self.f.a, self.f.ad_a, self.f.ad_b), (self.f.b, self.f.ad_b, self.f.ad_a)):
            ads = self.request('GET', self.account(self.f.ads, company) + '/ads')['ads']
            self.assertEqual({r['ad_item_id'] for r in ads}, {str(own), str(self.f.unassigned)})
            self.assertTrue(next(r['assigned'] for r in ads if r['ad_item_id'] == str(own)))
            for row in ads:
                self.assertEqual(set(row), {'ad_item_id', 'display_name', 'assigned'})
            for value in (str(other), str(self.f.creative), 'SIBLING PRIVATE', 'impressions', 'snapshot'):
                self.assertNotIn(value, json.dumps(ads))
            self.assertEqual([r['item_id'] for r in repo.performance(self.f.db, self.f.connection, company, self.f.creative)], [own])
            self.assertNotIn('SIBLING PRIVATE', str(repo.ad_assets(self.f.db, self.f.connection, company, own)))

    def test_archived_ownership_frozen_until_restore(self):
        self.f.shared_setup()
        self.request('POST', self.base + '/archive')
        for method, path, body in (
            ('PUT', self.account(self.f.fb), None), ('DELETE', self.account(self.f.ads), None),
            ('PUT', self.ad(self.f.unassigned), None), ('DELETE', self.ad(self.f.ad_a), None),
            ('GET', self.account(self.f.ads) + '/ads', None),
            ('POST', self.ad(self.f.ad_a) + '/reassign', {'target_company_id': str(self.f.b)}),
            ('POST', self.ad(self.f.ad_b, self.f.b) + '/reassign', {'target_company_id': str(self.f.a)}),
        ):
            self.request(method, path, 403, **({'json': body} if body else {}))
        self.request('POST', self.base + '/restore')
        self.request('PUT', self.account(self.f.fb))
        self.request('DELETE', self.ad(self.f.ad_a))
        self.request('DELETE', self.account(self.f.ads))

    def test_foreign_unknown_companies_and_resources_fail_closed(self):
        self.f.shared_setup()
        for company in (self.f.foreign_company, uuid4()):
            path = f'/api/companies/{company}'
            for method, suffix, body in (
                ('GET', '', None), ('PATCH', '', {'name': 'Hacked'}),
                ('POST', '/archive', None), ('POST', '/restore', None),
                ('PUT', f'/accounts/{self.f.fb}', None), ('DELETE', f'/accounts/{self.f.ads}', None),
                ('GET', f'/accounts/{self.f.ads}/ads', None),
                ('PUT', f'/ads/{self.f.ad_a}', None), ('DELETE', f'/ads/{self.f.ad_a}', None),
                ('POST', f'/ads/{self.f.ad_a}/reassign', {'target_company_id': str(self.f.b)}),
            ):
                self.request(method, path + suffix, 403, **({'json': body} if body else {}))
            self.request('POST', self.ad(self.f.ad_a) + '/reassign', 403, json={'target_company_id': str(company)})
        for account in (self.f.foreign_ads, uuid4()):
            for method, suffix in (('PUT', ''), ('DELETE', ''), ('GET', '/ads')):
                self.request(method, self.account(account) + suffix, 404)
        for ad in (self.f.foreign_ad, self.f.creative, uuid4()):
            for method in ('PUT', 'DELETE'):
                self.request(method, self.ad(ad), 404)
        self.assertIn(self.f.ad_a, self.f.ids(self.f.a))

    def test_authentication_and_membership_fenced_through_commit(self):
        original = repo.rename_company
        def rename(db, *args):
            with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                other.execute("SET LOCAL lock_timeout='50ms'")
                other.execute('DELETE FROM company_memberships')
            return original(db, *args)
        with patch('app.company_routes.repo.rename_company', side_effect=rename):
            self.request('PATCH', self.base, json={'name': 'Locked'})
        self.f.db.execute('DELETE FROM meta_sessions')
        self.f.db.execute("UPDATE meta_connections SET status='disconnected'")
        self.client.cookies.clear()
        self.request('GET', '/api/companies')
        self.request('POST', '/api/companies', 201, json={'name': 'Without Meta'})
        del self.client.headers['Authorization']
        self.request('GET', '/api/companies', 401)

    def test_ownership_api_invalidates_profiles_and_conflicts_roll_back(self):
        def versions(company):
            return {r['scope']: (r['input_revision'], r['suppressed']) for r in
                    self.f.db.execute('SELECT * FROM company_profiles WHERE company_id=%s', (company,)).fetchall()}
        self.request('PUT', self.account(self.f.ads))
        before = versions(self.f.a)
        self.assertEqual(len(before), 4)
        self.request('PUT', self.ad(self.f.ad_a))
        after = versions(self.f.a)
        self.assertTrue(all(after[scope][0] == before[scope][0] + 1 for scope in before))
        self.request('DELETE', self.account(self.f.ads), 409)
        self.assertEqual(versions(self.f.a), after)
        self.request('DELETE', self.ad(self.f.ad_a))
        removed = versions(self.f.a)
        self.assertTrue(all(removed[scope][0] == after[scope][0] + 1 and removed[scope][1] for scope in after))

    def test_storage_errors_are_generic(self):
        with patch('app.company_routes.library.database',
                   side_effect=psycopg.OperationalError('provider-secret database detail')):
            response = self.request('GET', '/api/companies', 503)
        self.assertEqual(response, {'detail': 'Company management is unavailable.'})

    def test_concurrent_api_mutations_do_not_deadlock(self):
        def create(index):
            return self.client.post('/api/companies', json={'name': f'Concurrent {index}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(create, range(2))), [201, 402])

    def test_v8_organic_limit_ads_unlink_and_downgrade(self):
        self.f.db.execute("UPDATE company_billing SET plan_code='free' WHERE company_id=%s", (self.f.a,))
        self.request('PUT', self.account(self.f.fb))
        self.request('PUT', self.account(self.f.ads))
        blocked = self.request('PUT', self.account(self.f.ig), 402)
        self.assertEqual(blocked['detail']['code'], 'organic_account_limit_reached')
        self.request('DELETE', self.account(self.f.fb))
        self.request('PUT', self.account(self.f.ig))
        self.f.db.execute("UPDATE company_billing SET plan_code='pro' WHERE company_id=%s", (self.f.a,))
        self.request('PUT', self.account(self.f.fb))
        self.f.db.execute("UPDATE company_billing SET plan_code='free' WHERE company_id=%s", (self.f.a,))
        self.assertEqual(len(self.request('GET', self.base)['accounts']), 3)
        extra = self.f.account('facebook', 'downgrade-extra')
        self.request('PUT', self.account(extra), 402)

    def test_v8_pro_sixth_organic_link_and_concurrent_free_race(self):
        accounts = [self.f.fb, self.f.ig] + [self.f.account('facebook', f'pro-{i}') for i in range(4)]
        for account in accounts[:5]:
            self.request('PUT', self.account(account))
        self.request('PUT', self.account(accounts[5]), 402)
        for account in accounts[:5]:
            self.request('DELETE', self.account(account))
        self.f.db.execute("UPDATE company_billing SET plan_code='free' WHERE company_id=%s", (self.f.a,))
        def link(account):
            return self.client.put(self.account(account)).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(link, accounts[:2])), [200, 402])
        self.assertEqual(self.f.db.execute('''SELECT count(*) AS n FROM company_accounts
            WHERE company_id=%s AND account_platform IN ('facebook','instagram')''',
            (self.f.a,)).fetchone()['n'], 1)

    def test_v8_analysis_api_quota_idempotency_and_worker_refund(self):
        self.f.db.execute("UPDATE company_billing SET plan_code='free' WHERE company_id=%s", (self.f.a,))
        self.request('PUT', self.account(self.f.fb))
        items = [self.f.organic] + [self.f.item(self.f.fb, f'quota-{i}', 'video', 'facebook')
                                     for i in range(3)]
        path = self.base + '/content/analyze'
        for item in items[:3]:
            self.request('POST', path, 202, json={'item_id': str(item)})
        self.request('POST', path, 202, json={'item_id': str(items[0])})
        blocked = self.request('POST', path, 402, json={'item_id': str(items[3])})
        self.assertEqual(blocked['detail']['code'], 'analysis_limit_reached')
        legacy = self.client.post('/api/meta/library/analyze',
                                  json={'item_ids': [str(items[3])]})
        self.assertEqual(legacy.status_code, 402, legacy.text)
        state = self.request('GET', self.base + '/billing')
        self.assertEqual(state['usage']['analyses'], 3)
        self.request('GET', self.base + '/content')
        self.request('POST', self.base + '/profiles/shared/refresh', 202,
                     headers={'Idempotency-Key': 'quota-read-profile'})
        self.assertEqual(self.request('GET', self.base + '/billing')['usage']['analyses'], 3)
        job = self.f.db.execute("SELECT id FROM meta_jobs WHERE item_id=%s AND kind='analysis'",
                                (items[0],)).fetchone()['id']
        claim = uuid4()
        self.f.db.execute("UPDATE meta_jobs SET state='running',claim=%s WHERE id=%s", (claim, job))
        operation = {'id': job, 'claim': claim, 'kind': 'analysis'}
        worker.finish(operation, 'failed')
        worker.finish(operation, 'failed')
        self.assertEqual(self.request('GET', self.base + '/billing')['usage']['analyses'], 2)
        completed = self.f.db.execute("SELECT id FROM meta_jobs WHERE item_id=%s AND kind='analysis'",
                                      (items[1],)).fetchone()['id']
        completed_claim = uuid4()
        self.f.db.execute("UPDATE meta_jobs SET state='running',claim=%s WHERE id=%s",
                          (completed_claim, completed))
        worker.finish({'id': completed, 'claim': completed_claim, 'kind': 'analysis'}, 'completed')
        self.assertEqual(self.request('GET', self.base + '/billing')['usage']['analyses'], 2)
        self.assertEqual(self.client.post('/api/meta/library/analyze',
            json={'item_ids': [str(items[3])]}).status_code, 202)

    def test_public_projection_uses_internal_ids_and_friendly_names(self):
        self.f.db.execute("UPDATE meta_accounts SET label='Friendly account' WHERE id=%s", (self.f.fb,))
        self.f.db.execute("UPDATE meta_accounts SET label='https://provider.invalid/private' WHERE id=%s", (self.f.ads,))
        self.request('PUT', self.account(self.f.fb))
        self.request('PUT', self.account(self.f.ads))
        payloads = [self.request('GET', '/api/companies?include_archived=true'),
                    self.request('GET', '/api/meta/accounts'), self.request('GET', self.base),
                    self.request('GET', self.account(self.f.ads) + '/ads')]
        encoded = json.dumps(payloads)
        for forbidden in ('external_id', 'connection_id', 'token', 'encrypted', 'https://',
                          'a-secret', 'b-secret', 'unassigned-secret', 'foreign-ads', str(self.f.foreign_company)):
            self.assertNotIn(forbidden, encoded)
        self.assertIn('Friendly account', encoded)
        self.assertIn('Meta Ads account', encoded)
        for account in payloads[1]['accounts']:
            self.assertEqual(set(account), {'account_id', 'platform', 'display_name', 'organic_owner'})


if __name__ == '__main__':
    unittest.main()
