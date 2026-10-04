"""V8 company billing against fresh and upgraded disposable PostgreSQL."""

import hashlib
import hmac
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient
from app.auth import get_token_verifier
from app.main import app
from app import auth_repository, billing_repository as billing, billing_routes
from auth_fixtures import USER_ID, OTHER_USER_ID
import test_auth_database


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class BillingTests(unittest.TestCase):
    def setUp(self):
        self.f = test_auth_database.AuthDatabaseTests('test_fresh_schema_company_creation_and_membership')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.db = self.f.db
        self.owner = self.f.create()
        self.foreign = self.f.create(OTHER_USER_ID)
        self.db.execute('''INSERT INTO company_memberships(company_id,user_id,role)
            VALUES (%s,%s,'member')''', (self.owner, OTHER_USER_ID))
        app.dependency_overrides[get_token_verifier] = lambda: self.f.auth.verifier
        self.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)
        env = patch.dict(os.environ, {'STRIPE_SECRET_KEY': 'sk_test_fake',
            'STRIPE_WEBHOOK_SECRET': 'whsec_test', 'STRIPE_PRO_MONTHLY_PRICE_ID': 'price_pro',
            'APP_ORIGIN': 'https://example.test'})
        env.start()
        self.addCleanup(env.stop)

    def call(self, method, path, *, user=USER_ID, **kwargs):
        headers = kwargs.pop('headers', {})
        if user:
            headers['Authorization'] = 'Bearer ' + self.f.auth.token(sub=str(user))
        return self.client.request(method, path, headers=headers, **kwargs)

    def path(self, suffix=''):
        return f'/api/companies/{self.owner}/billing{suffix}'

    def subscription(self, status='active', *, customer='cus_test', sub='sub_test', start=None, end=None):
        now = int(time.time())
        return {'id': sub, 'customer': customer, 'status': status,
                'cancel_at_period_end': False,
                'items': {'data': [{'price': {'id': 'price_pro'}, 'quantity': 1,
                                    'current_period_start': start or now-100,
                                    'current_period_end': end or now+20000}]}}

    def event(self, kind, obj, *, event_id=None):
        body = json.dumps({'id': event_id or 'evt_' + uuid4().hex,
                           'type': kind, 'data': {'object': obj}}).encode()
        stamp = str(int(time.time()))
        digest = hmac.new(b'whsec_test', stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
        if kind in ('customer.subscription.created', 'customer.subscription.updated'):
            with patch.object(billing_routes.stripe, 'retrieve_subscription', return_value=obj):
                return self.client.post('/api/stripe/webhook', content=body,
                    headers={'Stripe-Signature': f't={stamp},v1={digest}'})
        return self.client.post('/api/stripe/webhook', content=body,
            headers={'Stripe-Signature': f't={stamp},v1={digest}'})

    def mapped(self):
        with self.db.transaction():
            billing.initialize(self.db, self.owner)
            self.db.execute('UPDATE company_billing SET stripe_customer_id=%s WHERE company_id=%s',
                            ('cus_test', self.owner))

    def test_read_authorization_and_free_period(self):
        self.assertEqual(self.call('GET', self.path(), user=None).status_code, 401)
        self.assertEqual(self.call('GET', f'/api/companies/{self.foreign}/billing').status_code, 403)
        member = self.call('GET', self.path(), user=OTHER_USER_ID)
        self.assertEqual(member.status_code, 200, member.text)
        self.assertEqual(member.json()['effective_plan'], 'free')
        self.assertFalse(member.json()['can_manage_billing'])
        self.assertEqual(member.json()['entitlements'], billing.LIMITS['free'])
        self.assertTrue(self.call('GET', self.path()).json()['can_manage_billing'])
        row = self.db.execute('SELECT * FROM company_billing WHERE company_id=%s', (self.owner,)).fetchone()
        self.assertGreater(row['current_period_end'], row['current_period_start'])

    def test_checkout_and_portal_authorization_and_server_values(self):
        self.assertEqual(self.call('POST', self.path('/checkout'), user=OTHER_USER_ID).status_code, 403)
        self.assertEqual(self.call('POST', self.path('/portal'), user=OTHER_USER_ID).status_code, 403)
        with patch.dict(os.environ, {'STRIPE_PRO_MONTHLY_PRICE_ID': '', 'APP_ORIGIN': ''}):
            self.assertEqual(self.call('POST', f'/api/companies/{self.foreign}/billing/checkout').status_code, 403)
            self.assertEqual(self.call('POST', f'/api/companies/{self.foreign}/billing/portal').status_code, 403)
        open_session = {'customer': 'cus_test', 'mode': 'subscription',
            'client_reference_id': str(self.owner),
            'metadata': {'contentmetric_company_id': str(self.owner)},
            'url': 'https://checkout.stripe.com/pay/test'}
        with patch.object(billing_routes.stripe, 'create_customer', return_value={'id': 'cus_test'}) as customer, \
             patch.object(billing_routes.stripe, 'open_checkout_sessions', side_effect=[[], [open_session]]), \
             patch.object(billing_routes.stripe, 'current_subscriptions', return_value=[]), \
             patch.object(billing_routes.stripe, 'create_checkout', return_value={
                 'url': 'https://checkout.stripe.com/pay/test'}) as checkout:
            for _ in range(2):
                result = self.call('POST', self.path('/checkout'), json={
                    'price_id': 'price_attacker', 'stripe_customer_id': 'cus_attacker',
                    'stripe_subscription_id': 'sub_attacker'})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json(), {'url': 'https://checkout.stripe.com/pay/test'})
            customer.assert_called_once_with(self.owner)
            self.assertEqual(checkout.call_count, 1)
            self.assertEqual(checkout.call_args.args[:3], (self.owner, 'cus_test', 'price_pro'))
            self.assertEqual(self.db.execute('SELECT stripe_subscription_id FROM company_billing WHERE company_id=%s',
                                             (self.owner,)).fetchone()['stripe_subscription_id'], None)
        with patch.object(billing_routes.stripe, 'create_portal', return_value={
                'url': 'https://billing.stripe.com/session/test'}) as portal:
            self.assertEqual(self.call('POST', self.path('/portal')).status_code, 200)
            portal.assert_called_once_with('cus_test', 'https://example.test')

    def test_old_open_checkout_is_reused_and_completed_subscription_blocks_new_checkout(self):
        self.mapped()
        old = {'customer': 'cus_test', 'mode': 'subscription',
            'client_reference_id': str(self.owner),
            'metadata': {'contentmetric_company_id': str(self.owner)},
            'url': 'https://checkout.stripe.com/pay/old'}
        with patch.object(billing_routes.stripe, 'open_checkout_sessions', return_value=[old]), \
             patch.object(billing_routes.stripe, 'current_subscriptions', return_value=[]), \
             patch.object(billing_routes.stripe, 'create_checkout') as create:
            for _ in range(2):
                self.assertEqual(self.call('POST', self.path('/checkout')).json(), {'url': old['url']})
            create.assert_not_called()
        # A completed Session may precede webhook delivery. Stripe's subscription
        # blocks another purchase even while the local effective plan is Free.
        with patch.object(billing_routes.stripe, 'open_checkout_sessions', return_value=[]), \
             patch.object(billing_routes.stripe, 'current_subscriptions',
                          return_value=[{'status': 'active'}]), \
             patch.object(billing_routes.stripe, 'create_checkout') as create:
            self.assertEqual(self.call('POST', self.path('/checkout')).status_code, 409)
            create.assert_not_called()

    def test_expired_checkout_uses_new_attempt_key(self):
        self.mapped()
        with patch.object(billing_routes.stripe, 'open_checkout_sessions', return_value=[]), \
             patch.object(billing_routes.stripe, 'current_subscriptions', return_value=[]), \
             patch.object(billing_routes.stripe, 'create_checkout', return_value={
                 'url': 'https://checkout.stripe.com/pay/new'}) as create:
            self.assertEqual(self.call('POST', self.path('/checkout')).status_code, 200)
            self.assertEqual(self.call('POST', self.path('/checkout')).status_code, 200)
            self.assertNotEqual(create.call_args_list[0].kwargs['idempotency_key'],
                                create.call_args_list[1].kwargs['idempotency_key'])

    def test_checkout_provider_lists_are_customer_scoped_and_fail_closed(self):
        with patch.object(billing_routes.stripe, 'request', return_value={
            'data': [], 'has_more': False}) as send:
            self.assertEqual(billing_routes.stripe.open_checkout_sessions('cus_test'), [])
            self.assertEqual(send.call_args.kwargs['params'], {
                'customer': 'cus_test', 'status': 'open', 'limit': 100})
            self.assertEqual(billing_routes.stripe.current_subscriptions('cus_test'), [])
            self.assertEqual(send.call_args.kwargs['params'], {
                'customer': 'cus_test', 'limit': 100})
        with patch.object(billing_routes.stripe, 'request', return_value={
            'data': [], 'has_more': True}):
            with self.assertRaises(billing_routes.stripe.StripeError):
                billing_routes.stripe.open_checkout_sessions('cus_test')
            with self.assertRaises(billing_routes.stripe.StripeError):
                billing_routes.stripe.current_subscriptions('cus_test')

    def test_signature_duplicate_and_transaction_retry(self):
        self.mapped()
        obj = self.subscription()
        self.assertEqual(self.client.post('/api/stripe/webhook', json={}).status_code, 400)
        self.assertEqual(self.client.post('/api/stripe/webhook', content=b'{}',
                         headers={'Stripe-Signature': 't=1,v1=bad'}).status_code, 400)
        event_id = 'evt_retry'
        bad = {**obj, 'items': {'data': []}}
        self.assertEqual(self.event('customer.subscription.created', bad, event_id=event_id).status_code, 503)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM stripe_webhook_events').fetchone()['n'], 0)
        self.assertTrue(self.event('customer.subscription.created', obj, event_id=event_id).json()['processed'])
        self.assertFalse(self.event('customer.subscription.created', obj, event_id=event_id).json()['processed'])
        self.assertEqual(self.db.execute('SELECT count(*) n FROM stripe_webhook_events').fetchone()['n'], 1)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')

    def test_checkout_webhook_and_trialing(self):
        self.mapped()
        session = {'customer': 'cus_test', 'mode': 'subscription',
                   'client_reference_id': str(self.owner), 'subscription': 'sub_test'}
        with patch.object(billing_routes.stripe, 'retrieve_subscription',
                          return_value=self.subscription('trialing')):
            self.assertEqual(self.event('checkout.session.completed', session).status_code, 200)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')
        bad = {**session, 'client_reference_id': str(self.foreign)}
        with patch.object(billing_routes.stripe, 'retrieve_subscription',
                          return_value=self.subscription()):
            self.assertEqual(self.event('checkout.session.completed', bad).status_code, 503)

    def test_portal_without_customer_and_untrusted_origin(self):
        self.assertEqual(self.call('POST', self.path('/portal')).status_code, 409)
        with patch.dict(os.environ, {'APP_ORIGIN': 'https://attacker.test/path'}):
            self.assertEqual(self.call('POST', self.path('/checkout'),
                headers={'Origin': 'https://attacker.test'}).status_code, 503)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM company_billing WHERE company_id=%s',
                                         (self.owner,)).fetchone()['n'], 0)

    def test_checkout_tax_setting_is_server_side(self):
        with patch.object(billing_routes.stripe, 'request', return_value={'url': 'ok'}) as send:
            with patch.dict(os.environ, {'STRIPE_AUTOMATIC_TAX': 'true'}):
                billing_routes.stripe.create_checkout(self.owner, 'cus_test', 'price_pro', 'https://example.test')
            self.assertEqual(send.call_args.kwargs['data']['automatic_tax[enabled]'], 'true')
            with patch.dict(os.environ, {'STRIPE_AUTOMATIC_TAX': ''}):
                billing_routes.stripe.create_checkout(self.owner, 'cus_test', 'price_pro', 'https://example.test')
            self.assertNotIn('automatic_tax[enabled]', send.call_args.kwargs['data'])

    def test_lifecycle_grace_cancellation_and_data_retention(self):
        self.mapped()
        self.assertEqual(self.event('customer.subscription.created', self.subscription()).status_code, 200)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')
        with patch.object(billing_routes.stripe, 'retrieve_subscription',
                          return_value=self.subscription('past_due')):
            self.assertEqual(self.event('invoice.payment_failed', {
                'customer': 'cus_test', 'subscription': 'sub_test'}).status_code, 200)
            first = self.db.execute('SELECT grace_until FROM company_billing WHERE company_id=%s',
                                    (self.owner,)).fetchone()['grace_until']
            self.event('invoice.payment_failed', {'customer': 'cus_test', 'subscription': 'sub_test'})
        self.assertEqual(first, self.db.execute('SELECT grace_until FROM company_billing WHERE company_id=%s',
                                                (self.owner,)).fetchone()['grace_until'])
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')
        self.db.execute('UPDATE company_billing SET grace_until=now()-interval \'1 second\' WHERE company_id=%s',
                        (self.owner,))
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'free')
        with patch.object(billing_routes.stripe, 'retrieve_subscription',
                          return_value=self.subscription('past_due')):
            self.event('invoice.payment_failed', {'customer': 'cus_test', 'subscription': 'sub_test'})
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'free')
        with patch.object(billing_routes.stripe, 'retrieve_subscription',
                          return_value=self.subscription('active')):
            self.assertEqual(self.event('invoice.paid', {'customer': 'cus_test',
                'subscription': 'sub_test'}).status_code, 200)
        self.assertIsNone(self.db.execute('SELECT grace_until FROM company_billing WHERE company_id=%s',
                                          (self.owner,)).fetchone()['grace_until'])
        canceled = self.subscription('canceled')
        canceled['cancel_at_period_end'] = True
        self.event('customer.subscription.updated', canceled)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')
        self.assertTrue(self.call('GET', self.path()).json()['cancel_at_period_end'])
        self.event('customer.subscription.deleted', canceled)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'free')
        self.assertIsNotNone(self.db.execute('SELECT id FROM companies WHERE id=%s', (self.owner,)).fetchone())

    def test_no_access_for_incomplete_unpaid_and_wrong_price(self):
        self.mapped()
        for status in ('incomplete', 'unpaid', 'incomplete_expired'):
            response = self.event('customer.subscription.updated', self.subscription(status))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'free')
        invalid = self.subscription()
        invalid['items']['data'][0]['price']['id'] = 'price_other'
        self.assertEqual(self.event('customer.subscription.updated', invalid).status_code, 503)

    def test_expired_mirrored_period_starts_free_until_renewal(self):
        self.mapped()
        now = int(time.time())
        expired = self.subscription('active', start=now-40000, end=now-100)
        self.assertEqual(self.event('customer.subscription.updated', expired).status_code, 200)
        state = self.call('GET', self.path()).json()
        self.assertEqual(state['effective_plan'], 'free')
        self.assertEqual(state['plan'], 'free')
        self.assertEqual(self.event('customer.subscription.updated', self.subscription('active')).status_code, 200)
        self.assertEqual(self.call('GET', self.path()).json()['effective_plan'], 'pro')

    def test_usage_period_ledger_and_replay(self):
        now = datetime.now(timezone.utc)
        with self.db.transaction():
            row = billing.initialize(self.db, self.owner, at=now-timedelta(days=40))
            old_start = row['current_period_start']
            billing.record_usage(self.db, self.owner, 'analysis', 1, 'analysis:old:reserve',
                                 'analysis_job', 'old', 'reserve', at=old_start)
            row = billing.initialize(self.db, self.owner, at=now)
            self.assertGreater(row['current_period_start'], old_start)
            for _ in range(2):
                billing.record_usage(self.db, self.owner, 'analysis', 1, 'analysis:new:reserve',
                                     'analysis_job', 'new', 'reserve', at=now)
            billing.record_usage(self.db, self.owner, 'analysis', -1, 'analysis:new:refund',
                                 'analysis_job', 'new', 'refund', at=now)
            self.assertEqual(billing.usage(self.db, row)['analyses'], 0)
            with self.assertRaises(ValueError):
                billing.record_usage(self.db, self.foreign, 'analysis', 1, 'analysis:new:reserve',
                                     'analysis_job', 'new', 'reserve', at=now)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM company_usage_ledger').fetchone()['n'], 3)
        with self.assertRaises(psycopg.Error), self.db.transaction():
            self.db.execute('DELETE FROM company_usage_ledger')

    def test_migration_rollback_and_rls(self):
        migration = Path(__file__).resolve().parents[1]/'migrations/014_billing_foundation.sql'
        with self.assertRaises(psycopg.errors.DuplicateTable):
            self.db.execute(migration.read_text())
        self.db.execute('ROLLBACK')
        for name in ('company_billing','company_usage_ledger','stripe_webhook_events'):
            self.assertTrue(self.db.execute('''SELECT relrowsecurity FROM pg_class WHERE relname=%s''',
                                            (name,)).fetchone()['relrowsecurity'])
            self.assertEqual(self.db.execute('''SELECT count(*) n FROM pg_policies
                WHERE schemaname=%s AND tablename=%s''', (self.f.schema, name)).fetchone()['n'], 0)
        role = 'v8_reader_' + uuid4().hex
        self.f.admin.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role)))
        try:
            self.f.admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(self.f.schema), sql.Identifier(role)))
            for name in ('company_billing','company_usage_ledger','stripe_webhook_events'):
                self.f.admin.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(
                    sql.Identifier(self.f.schema), sql.Identifier(name), sql.Identifier(role)))
            self.db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
            for name in ('company_billing','company_usage_ledger','stripe_webhook_events'):
                self.assertEqual(self.db.execute(sql.SQL('SELECT count(*) n FROM {}').format(
                    sql.Identifier(name))).fetchone()['n'], 0)
        finally:
            self.db.execute('RESET ROLE')
            self.f.admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            self.f.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

    def test_concurrent_reservation_same_key(self):
        def reserve(_):
            with psycopg.connect(self.f.url, row_factory=dict_row) as db:
                with db.transaction():
                    return billing.record_usage(db, self.owner, 'idea_generation', 1,
                        'idea:shared:reserve', 'generation_request', 'shared', 'reserve')['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(reserve, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.db.execute('SELECT count(*) n FROM company_usage_ledger').fetchone()['n'], 1)

    def test_populated_v7_to_v8_migration(self):
        schema = 'billing_upgrade_' + uuid4().hex
        self.f.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        self.addCleanup(lambda: self.f.admin.execute(
            sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema))))
        url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={schema}')
        files = sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql'))
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as db:
            for file in files[:-1]:
                db.execute(file.read_text())
            company = auth_repository.create_company_for_user(db, uuid4(), 'Legacy')['id']
            db.execute('INSERT INTO user_onboarding_state(user_id) SELECT user_id FROM company_memberships WHERE company_id=%s',
                       (company,))
            db.execute(files[-1].read_text())
            self.assertIsNone(db.execute('SELECT * FROM company_billing WHERE company_id=%s',
                                         (company,)).fetchone())
            with db.transaction():
                row = billing.initialize(db, company)
            self.assertEqual(row['plan_code'], 'free')
            self.assertEqual(db.execute('SELECT count(*) n FROM user_onboarding_state').fetchone()['n'], 1)
