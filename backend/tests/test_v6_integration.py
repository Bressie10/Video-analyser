"""Integration-only route inventory, upload IDOR, provider/session and role contracts."""
import unittest
from unittest.mock import patch
from uuid import UUID
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_token_verifier
from app import tiktok
from app.video_repository import save_analysis, save_performance
from auth_fixtures import USER_ID, OTHER_USER_ID
import test_auth_database
from test_recommendations_api import ANALYSIS

class IntegrationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.f = test_auth_database.AuthDatabaseTests('test_fresh_schema_company_creation_and_membership')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        app.dependency_overrides[get_token_verifier] = lambda: self.f.auth.verifier
        self.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        self.api = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.api.close)

    def login(self, user=USER_ID):
        self.api.headers['Authorization'] = 'Bearer '+self.f.auth.token(sub=str(user))

    def test_all_application_routes_require_identity(self):
        # Stripe authenticates its public callback with the raw-body signature.
        public = {'/health', '/health/db', '/api/meta/callback', '/api/tiktok/callback',
                  '/api/stripe/webhook'}
        # Real route requests, including valid UUID syntax; authentication precedes body validation.
        import re
        for template, methods in app.openapi()['paths'].items():
            if template in public: continue
            path = re.sub(r'\{[^}]+\}', str(USER_ID), template)
            for method in methods:
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.api.request(method, path).status_code, 401)

    def test_uploads_are_owned_and_legacy_and_cross_user_ids_are_hidden(self):
        legacy = save_analysis(ANALYSIS)
        self.login()
        with patch('app.main.analyze_file', return_value=ANALYSIS):
            response = self.api.post('/api/videos', files={'video': ('sample.mp4', b'fixture', 'video/mp4')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('no-store', response.headers['cache-control'])
        video = response.json()['video_id']
        self.assertEqual(self.api.get(f'/api/videos/{video}/analysis').status_code, 200)
        self.assertEqual(self.f.db.execute('SELECT owner_user_id FROM videos WHERE id=%s', (video,)).fetchone()['owner_user_id'], USER_ID)
        for identity in (USER_ID, OTHER_USER_ID):
            self.login(identity)
            self.assertEqual(self.api.get(f'/api/videos/{legacy}/analysis').status_code, 404)
        for endpoint, method in [('analysis','GET'), ('recommendations','POST')]:
            self.assertEqual(self.api.request(method, f'/api/videos/{video}/{endpoint}').status_code, 404)
        snapshot = {'performance_source':'facebook','performance_metrics':{'view_count':2}}
        self.assertFalse(save_performance(UUID(video), snapshot, owner_user_id=OTHER_USER_ID))
        self.assertTrue(save_performance(UUID(video), snapshot, owner_user_id=USER_ID))

    def test_roles_are_projected_without_meta_and_me_is_safe(self):
        self.login()
        me = self.api.get('/api/me')
        self.assertEqual(set(me.json()), {'user_id','email','profile'})
        company = self.api.post('/api/companies', json={'name':'Disconnected'}).json()
        self.assertEqual(company['role'], 'owner')
        self.f.db.execute("UPDATE company_memberships SET role='member' WHERE company_id=%s", (company['company_id'],))
        self.assertEqual(self.api.get('/api/companies').json()['companies'][0]['role'], 'member')
        self.assertEqual(self.api.get('/api/companies/'+company['company_id']).json()['role'], 'member')
        self.assertEqual(self.api.patch('/api/companies/'+company['company_id'], json={'name':'Denied'}).status_code, 403)

    def test_provider_expiry_is_distinct_from_app_authentication(self):
        self.login()
        response = self.api.get('/api/meta/library')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['X-ContentMetric-Auth'], 'provider')
        self.api.headers.pop('Authorization')
        response = self.api.get('/api/meta/library')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('X-ContentMetric-Auth', response.headers)

    def test_tiktok_state_and_session_cannot_cross_users(self):
        import time
        state = tiktok.begin_user_state(USER_ID)
        self.assertIsNone(tiktok.consume_user_state(state, 'wrong'))
        self.assertIsNone(tiktok.consume_user_state('☃', state))
        self.assertEqual(tiktok.consume_user_state(state, state), USER_ID)
        self.assertIsNone(tiktok.consume_user_state(state, state))
        state = tiktok.begin_user_state(USER_ID)
        with patch('app.tiktok.time.time', return_value=time.time()+601):
            self.assertIsNone(tiktok.consume_user_state(state, state))
        session = tiktok.create_session(tiktok.UserTokens('secret', None, time.time()+3600, 0), owner_user_id=USER_ID)
        with self.assertRaises(tiktok.TikTokNotConnected):
            tiktok.access_token_for_session(session, None, owner_user_id=OTHER_USER_ID)
        self.assertEqual(tiktok.access_token_for_session(session, None, owner_user_id=USER_ID), 'secret')

    def test_test_database_role_satisfies_rls_contract(self):
        row = self.f.db.execute("SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        self.assertTrue(row['rolsuper'] or row['rolbypassrls'])
        tables = self.f.db.execute("SELECT relname,relrowsecurity FROM pg_class WHERE relnamespace=%s::regnamespace AND relname IN ('user_profiles','company_memberships')", (self.f.schema,)).fetchall()
        self.assertTrue(all(t['relrowsecurity'] for t in tables))

class NewUserIntegrationTests(unittest.TestCase):
    def test_new_users_company_oauth_content_idea_and_cross_user_sequence(self):
        import test_meta_v6_auth
        from test_persistent_ideas import RESULT
        from uuid import uuid4
        f = test_meta_v6_auth.MetaV6Tests('test_auth_required_and_json_initiation')
        self.addCleanup(f.doCleanups); f.setUp()
        api = f.api
        api.headers.update(f.headers())
        self.assertEqual(api.get('/api/companies').json()['companies'], [])
        company = api.post('/api/companies', json={'name':'Company A'}).json()
        self.assertEqual(company['role'], 'owner')
        a = company['company_id']; base = '/api/companies/'+a
        self.assertEqual(api.get(base+'/content').json()['items'], [])
        connection = f.connect()
        self.assertEqual(connection['owner_user_id'], USER_ID)
        # Deterministic provider inventory/content fixture, with real SQL and API authorization.
        accounts=[]
        for platform in ('facebook','instagram'):
            account=f.db.execute("INSERT INTO meta_accounts(connection_id,platform,external_id,label) VALUES (%s,%s,%s,%s) RETURNING id", (connection['id'],platform,platform,platform)).fetchone()['id']
            self.assertEqual(api.put(base+'/accounts/'+str(account)).status_code,200)
            accounts.append(account)
        video=save_analysis(ANALYSIS)
        f.db.execute('UPDATE videos SET meta_connection_id=%s WHERE id=%s',(connection['id'],video))
        item=f.db.execute("INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,content_type,label,video_id,analysis_state,analysis_version) VALUES (%s,%s,'facebook','fixture-post','video','Fixture content',%s,'completed',1) RETURNING id",(connection['id'],accounts[0],video)).fetchone()['id']
        self.assertEqual(api.get(base+'/content').json()['items'][0]['library_item_id'],str(item))
        ideas='/api/meta/companies/'+a
        body={'request_id':str(uuid4()),'target_platforms':['facebook'],'video_ids':[str(item)]}
        with patch('app.idea_service.generate_idea',return_value=RESULT) as model:
            generated=api.post(ideas+'/recommendations',json=body)
            self.assertEqual(generated.status_code,200,generated.text)
            self.assertEqual(api.post(ideas+'/recommendations',json=body).json(),generated.json())
            self.assertEqual(model.call_count,1)
        idea=ideas+'/ideas/'+generated.json()['id']
        self.assertEqual(api.get(idea).status_code,200)
        self.assertEqual(api.patch(idea,json={'title':'Edited'}).status_code,200)
        self.assertEqual(api.put(idea+'/feedback',json={'feedback':'liked'}).status_code,200)
        self.assertEqual(api.patch(idea,json={'status':'used'}).status_code,200)
        self.assertEqual(api.put(idea+'/publications/'+str(item)).status_code,200)
        self.assertEqual(api.post(base+'/profiles/shared/refresh',headers={'Idempotency-Key':'integration'}).status_code,202)
        api.headers.update(f.headers(OTHER_USER_ID))
        self.assertEqual(api.get('/api/companies').json()['companies'],[])
        b=api.post('/api/companies',json={'name':'Company B'}).json()['company_id']
        self.assertEqual(api.get('/api/meta/test').status_code,403)
        self.assertEqual(api.put('/api/companies/'+b+'/accounts/'+str(accounts[0])).status_code,404)
        for path in (base,base+'/content',base+'/profiles',idea,idea+'/publications',ideas+'/publication-options'):
            self.assertEqual(api.get(path).status_code,403,path)
        api.headers.update(f.headers())
        self.assertEqual(api.get(base).status_code,200)
        self.assertEqual(api.get(idea).json()['title'],'Edited')

class DatabaseRoleTests(unittest.TestCase):
    def test_non_superuser_table_owner_works_and_granted_nonowner_is_rls_denied(self):
        import os
        import psycopg
        from psycopg import sql
        from pathlib import Path
        from uuid import uuid4
        owner='v6_owner_'+uuid4().hex; reader='v6_reader_'+uuid4().hex
        schema='v6_role_'+uuid4().hex
        with psycopg.connect(os.environ['TEST_DATABASE_URL'],autocommit=True) as db:
            try:
                for role in (owner,reader): db.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role)))
                db.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(sql.Identifier(schema),sql.Identifier(owner)))
                db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(owner)))
                db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                for path in sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql')): db.execute(path.read_text())
                db.execute('INSERT INTO user_profiles(user_id) VALUES (%s)',(USER_ID,))
                self.assertEqual(db.execute('SELECT count(*) FROM user_profiles').fetchone()[0],1)
                db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(reader)))
                db.execute(sql.SQL('GRANT SELECT,INSERT ON user_profiles,company_memberships TO {}').format(sql.Identifier(reader)))
                db.execute('RESET ROLE');db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(reader)))
                self.assertEqual(db.execute('SELECT count(*) FROM user_profiles').fetchone()[0],0)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): db.execute('INSERT INTO user_profiles(user_id) VALUES (%s)',(OTHER_USER_ID,))
            finally:
                db.execute('RESET ROLE')
                db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
                for role in (reader,owner): db.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
