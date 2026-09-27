"""V6 JWT/membership/IDOR matrix against real PostgreSQL and real adapters."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import psycopg
from app import company_ownership_repository as ownership
from app import meta_library_repository as library
from company_auth_fixtures import grant, USER_ID, OTHER_USER_ID
import test_idea_integration as integration


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration.IdeaIntegrationTests('test_real_adapter_shared_creative_and_profile_revisions')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.f = self.fixture.f
        self.client = self.fixture.client
        self.auth = self.fixture.fixture.auth
        # Save B's valid idea, then separate the two users' memberships.
        self.b_idea = self.fixture.generate(company=self.f.b)
        self.a_idea = self.fixture.generate()
        self.f.db.execute('DELETE FROM company_memberships WHERE company_id=%s', (self.f.b,))
        grant(self.f.db, [self.f.b], user_id=OTHER_USER_ID)
        self.company = f'/api/companies/{self.f.a}'
        self.ideas = f'/api/meta/companies/{self.f.a}'
        self.idea = self.ideas + '/ideas/' + self.a_idea['id']
        self.fixture.model.reset_mock()

    def endpoints(self, company=None):
        company = company or self.f.a
        base = f'/api/companies/{company}'
        ideas = f'/api/meta/companies/{company}'
        idea = ideas + '/ideas/' + self.a_idea['id']
        return [
            ('GET', base, {}), ('PATCH', base, {'json': {'name': 'New'}}),
            ('POST', base+'/archive', {}), ('POST', base+'/restore', {}),
            ('GET', base+'/content', {}), ('GET', base+'/profiles', {}),
            ('GET', base+'/profiles/shared', {}),
            ('POST', base+'/profiles/shared/refresh', {'headers': {'Idempotency-Key': str(uuid4())}}),
            ('PUT', base+f'/accounts/{self.f.fb}', {}),
            ('DELETE', base+f'/accounts/{self.f.fb}', {}),
            ('GET', base+f'/accounts/{self.f.ads}/ads', {}),
            ('PUT', base+f'/ads/{self.f.ad_a}', {}),
            ('DELETE', base+f'/ads/{self.f.ad_a}', {}),
            ('POST', base+f'/ads/{self.f.ad_a}/reassign', {'json': {'target_company_id': str(self.f.b)}}),
            ('POST', ideas+'/recommendations', {'json': {'request_id': str(uuid4()),
                'target_platforms': ['facebook'], 'video_ids': [str(self.f.creative)]}}),
            ('GET', ideas+'/ideas', {}), ('GET', ideas+'/publication-options', {}),
            ('GET', idea, {}), ('GET', idea+'/evidence', {}),
            ('PATCH', idea, {'json': {'title': 'New'}}),
            ('PATCH', idea, {'json': {'status': 'used'}}),
            ('PUT', idea+'/feedback', {'json': {'feedback': 'liked'}}),
            ('GET', idea+'/publications', {}),
            ('PUT', idea+f'/publications/{self.f.organic}', {}),
            ('DELETE', idea+f'/publications/{self.f.organic}', {}),
        ]

    def assert_endpoints(self, endpoints, expected):
        for method, path, kwargs in endpoints:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, **kwargs)
                self.assertEqual(response.status_code, expected, response.text)
                self.assertIn('no-store', response.headers['cache-control'])

    def test_all_families_require_valid_signed_user_even_with_meta_cookie(self):
        endpoints = self.endpoints() + [('GET', '/api/companies', {}),
            ('POST', '/api/companies', {'json': {'name': 'New'}}), ('GET', '/api/meta/accounts', {})]
        for token in (None, 'malformed', self.auth.token(exp=1), self.auth.token(aud='wrong')):
            self.client.headers.pop('Authorization', None)
            if token:
                self.client.headers['Authorization'] = 'Bearer '+token
            self.assert_endpoints(endpoints, 401)
        self.fixture.model.assert_not_called()

    def test_every_family_denies_unrelated_user_and_request_identity_spoofing(self):
        self.client.headers['Authorization'] = 'Bearer '+self.auth.token(sub=str(OTHER_USER_ID))
        self.client.headers['X-User-ID'] = str(USER_ID)
        self.client.cookies.set('selected_company', str(self.f.a))
        self.assert_endpoints(self.endpoints(), 403)
        self.fixture.model.assert_not_called()

    def test_lists_memberships_only_and_never_claims_legacy(self):
        legacy = ownership.create_company(self.f.db, self.f.connection, 'Unclaimed')['id']
        for token, expected in ((self.auth.token(), self.f.a), (self.auth.token(sub=str(OTHER_USER_ID)), self.f.b)):
            self.client.headers['Authorization'] = 'Bearer '+token
            self.assertEqual([r['company_id'] for r in self.client.get('/api/companies').json()['companies']], [str(expected)])
            self.assertEqual([r['id'] for r in self.client.get('/api/me/companies').json()['companies']], [str(expected)])
            self.assertEqual(self.client.get(f'/api/companies/{legacy}').status_code, 403)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM company_memberships WHERE company_id=%s', (legacy,)).fetchone()['n'], 0)

    def test_creation_is_disconnected_atomic_owner_and_keeps_response_contract(self):
        self.client.cookies.clear()
        result = self.client.post('/api/companies', json={'name': 'Fresh'})
        self.assertEqual(result.status_code, 201, result.text)
        identity = result.json()['company_id']
        self.assertEqual(set(result.json()), {'company_id', 'name', 'archived', 'accounts'})
        row = self.f.db.execute('''SELECT c.connection_id,m.user_id,m.role FROM companies c
            JOIN company_memberships m ON m.company_id=c.id WHERE c.id=%s''', (identity,)).fetchone()
        self.assertEqual(row, {'connection_id': None, 'user_id': USER_ID, 'role': 'owner'})
        self.assertEqual(self.client.get(f'/api/companies/{identity}/content').json(), {'items': [], 'next_offset': None})
        self.assertEqual(self.client.get(f'/api/companies/{identity}/profiles/shared').status_code, 200)
        self.assertEqual(self.client.post(f'/api/companies/{identity}/profiles/shared/refresh', headers={'Idempotency-Key': 'new'}).status_code, 202)
        # Failure after the foundation operation must roll its writes back too.
        before = self.f.db.execute('SELECT count(*) AS n FROM companies').fetchone()['n']
        with patch('app.company_routes.repo.company_summary', side_effect=psycopg.OperationalError('failure')):
            self.assertEqual(self.client.post('/api/companies', json={'name': 'Rollback'}).status_code, 503)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM companies').fetchone()['n'], before)

    def test_member_can_use_all_ordinary_operations_without_meta(self):
        grant(self.f.db, [self.f.a], role='member')
        self.client.cookies.clear()
        for path in (self.company, self.company+'/content', self.company+'/profiles',
                     self.company+'/profiles/shared', self.ideas+'/ideas', self.idea,
                     self.idea+'/evidence', self.idea+'/publications', self.ideas+'/publication-options'):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.post(self.company+'/profiles/shared/refresh', headers={'Idempotency-Key': 'member'}).status_code, 202)
        self.assertEqual(self.client.patch(self.idea, json={'title': 'Member edit'}).status_code, 200)
        self.assertEqual(self.client.patch(self.idea, json={'status': 'used'}).status_code, 200)
        self.assertEqual(self.client.put(self.idea+'/feedback', json={'feedback': 'liked'}).status_code, 200)
        self.assertEqual(self.client.put(self.idea+f'/publications/{self.f.organic}').status_code, 200)
        self.assertEqual(self.client.delete(self.idea+f'/publications/{self.f.organic}').status_code, 200)
        self.assertEqual(self.fixture.post().status_code, 200)

    def test_member_cannot_configure_or_reassign_company(self):
        grant(self.f.db, [self.f.a], role='member')
        endpoints = [entry for entry in self.endpoints() if entry[1].startswith(self.company)
                     and (entry[0] != 'GET' or entry[1].endswith('/ads'))
                     and '/profiles' not in entry[1]]
        self.assert_endpoints(endpoints, 403)
        self.assertIn(self.f.ad_a, self.f.ids(self.f.a))

    def test_valid_other_company_idea_uuid_rejected_for_every_action(self):
        foreign = self.ideas+'/ideas/'+self.b_idea['id']
        operations = [(method, path.replace(self.idea, foreign), kwargs)
                      for method, path, kwargs in self.endpoints() if path.startswith(self.idea)]
        self.assert_endpoints(operations, 404)
        own_history = self.client.get(self.ideas+'/ideas').json()['items']
        self.assertEqual([row['id'] for row in own_history], [self.a_idea['id']])
        self.assertEqual(self.client.get(self.ideas+'/ideas', params={'after': self.b_idea['id']}).status_code, 404)

    def test_valid_foreign_content_publication_and_profile_identifiers_fail(self):
        foreign_item = self.fixture.fixture.b_facebook
        self.assertEqual(self.fixture.post(ids=[foreign_item]).status_code, 404)
        self.assertEqual(self.client.put(self.idea+f'/publications/{foreign_item}').status_code, 404)
        self.assertEqual(self.client.get(self.ideas+'/publication-options', params={'after': str(foreign_item)}).status_code, 404)
        cards = self.client.get(self.company+'/content').json()['items']
        self.assertNotIn(str(foreign_item), [row['library_item_id'] for row in cards])
        self.assert_endpoints([e for e in self.endpoints(self.f.b) if '/profiles' in e[1]], 403)
        self.fixture.model.assert_not_called()

    def test_account_and_ad_idor_and_reassignment_requires_both_owner_roles(self):
        self.assertEqual(self.client.put(self.company+f'/accounts/{self.f.foreign_ads}').status_code, 404)
        self.assertEqual(self.client.put(self.company+f'/ads/{self.f.foreign_ad}').status_code, 404)
        self.assertEqual(self.client.put(self.company+f'/ads/{self.f.ad_b}').status_code, 409)
        path = self.company+f'/ads/{self.f.ad_a}/reassign'
        for role in (None, 'member'):
            if role:
                grant(self.f.db, [self.f.b], role=role)
            self.assertEqual(self.client.post(path, json={'target_company_id': str(self.f.b)}).status_code, 403)
            self.assertIn(self.f.ad_a, self.f.ids(self.f.a))
        grant(self.f.db, [self.f.b])
        self.assertEqual(self.client.post(path, json={'target_company_id': str(self.f.b)}).status_code, 200)
        self.assertIn(self.f.ad_a, self.f.ids(self.f.b))

    def test_link_binds_only_owned_connection_and_rolls_back_failed_binding(self):
        result = self.client.post('/api/companies', json={'name': 'Disconnected'}).json()
        identity = result['company_id']
        path = f'/api/companies/{identity}/accounts/'
        for account, expected in ((self.f.foreign_ads, 404), (self.f.fb, 409)):
            self.assertEqual(self.client.put(path+str(account)).status_code, expected)
            self.assertIsNone(self.f.db.execute('SELECT connection_id FROM companies WHERE id=%s', (identity,)).fetchone()['connection_id'])
        self.assertEqual(self.client.put(path+str(self.f.ads)).status_code, 200)
        self.assertEqual(self.f.db.execute('SELECT connection_id FROM companies WHERE id=%s', (identity,)).fetchone()['connection_id'], self.f.connection)
        self.f.db.execute('UPDATE meta_connections SET owner_user_id=NULL WHERE id=%s', (self.f.connection,))
        self.assertEqual(self.client.put(path+str(self.f.ads)).status_code, 404)
        self.assertEqual(self.client.get('/api/meta/accounts').json(), {'accounts': []})

    def test_archived_detail_and_listing_are_member_visible_but_use_is_denied(self):
        self.assertEqual(self.client.post(self.company+'/archive').status_code, 200)
        self.assertEqual(self.client.get('/api/companies').json(), {'companies': []})
        self.assertEqual(len(self.client.get('/api/companies?include_archived=true').json()['companies']), 1)
        grant(self.f.db, [self.f.a], role='member')
        self.assertEqual(self.client.get(self.company).status_code, 200)
        endpoints = [e for e in self.endpoints() if e[1] != self.company or e[0] != 'GET']
        self.assert_endpoints(endpoints, 403)
        grant(self.f.db, [self.f.a])
        self.assertEqual(self.client.post(self.company+'/restore').status_code, 200)

    def test_membership_and_owner_locks_survive_mutation_until_commit(self):
        original = ownership.reassign_ad
        grant(self.f.db, [self.f.b])
        def guarded(db, *args):
            for statement in ('DELETE FROM company_memberships', "UPDATE company_memberships SET role='member'"):
                with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                    other.execute("SET LOCAL lock_timeout='30ms'")
                    other.execute(statement)
            return original(db, *args)
        with patch('app.company_routes.repo.reassign_ad', side_effect=guarded):
            self.assertEqual(self.client.post(self.company+f'/ads/{self.f.ad_a}/reassign', json={'target_company_id': str(self.f.b)}).status_code, 200)

    def test_concurrent_opposite_reassignments_keep_lock_order(self):
        grant(self.f.db, [self.f.b])
        def move(args):
            source, target, ad = args
            return self.client.post(f'/api/companies/{source}/ads/{ad}/reassign', json={'target_company_id': str(target)}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(move, [(self.f.a,self.f.b,self.f.ad_a), (self.f.b,self.f.a,self.f.ad_b)])), [200,200])

    def test_account_picker_hides_unclaimed_company_metadata(self):
        legacy = ownership.create_company(self.f.db, self.f.connection, 'LEGACY PRIVATE')['id']
        ownership.reassign_organic_account(self.f.db, self.f.connection, self.f.a, legacy, self.f.fb)
        response = self.client.get('/api/meta/accounts')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('LEGACY PRIVATE', response.text)
        self.assertNotIn(str(legacy), response.text)
        self.assertNotIn(str(self.f.fb), response.text)
