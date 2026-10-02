"""V7 onboarding API and migration against disposable PostgreSQL."""

import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from app.auth import get_token_verifier
from app.main import app
from app import auth_repository
from app.meta_library_repository import ANALYSIS_VERSION
from auth_fixtures import USER_ID, OTHER_USER_ID
import test_auth_database


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.f = test_auth_database.AuthDatabaseTests('test_fresh_schema_company_creation_and_membership')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.db = self.f.db
        app.dependency_overrides[get_token_verifier] = lambda: self.f.auth.verifier
        self.addCleanup(lambda: app.dependency_overrides.pop(get_token_verifier, None))
        self.client = TestClient(app, base_url='https://testserver')
        self.addCleanup(self.client.close)

    def request(self, method='GET', path='/api/me/onboarding', user=USER_ID, **kwargs):
        return self.client.request(method, path,
            headers={'Authorization': 'Bearer '+self.f.auth.token(sub=str(user))}, **kwargs)

    def state(self, user=USER_ID):
        result = self.request(user=user)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers['cache-control'], 'private, no-store')
        return result.json()

    def connection(self, user=USER_ID, *, usable=True):
        auth_repository.ensure_profile(self.db, user)
        return self.db.execute('''INSERT INTO meta_connections
            (external_user_id,expires_at,token_ciphertext,owner_user_id,status)
            VALUES (%s,now()+interval '1 day',%s,%s,%s) RETURNING id''',
            (str(uuid4()), 'encrypted' if usable else None, user,
             'connected' if usable else 'disconnected')).fetchone()['id']

    def company(self, user=USER_ID):
        return self.f.create(user)

    def link(self, company, connection, platform):
        self.db.execute('UPDATE companies SET connection_id=%s WHERE id=%s', (connection, company))
        account = self.db.execute('''INSERT INTO meta_accounts(connection_id,platform,external_id,label)
            VALUES (%s,%s,%s,%s) RETURNING id''',
            (connection, platform, str(uuid4()), platform)).fetchone()['id']
        self.db.execute('''INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
            VALUES (%s,%s,%s,%s)''', (company, connection, account, platform))
        return account

    def item(self, connection, account, *, state='completed', version=ANALYSIS_VERSION):
        video = self.db.execute('''INSERT INTO videos(duration_seconds,container,file_size_bytes,
            meta_connection_id,analysis_version) VALUES (5,'mp4',100,%s,%s) RETURNING id''',
            (connection, version)).fetchone()['id']
        return self.db.execute('''INSERT INTO meta_library_items(connection_id,account_id,
            platform,external_id,content_type,label,video_id,analysis_state,analysis_version)
            VALUES (%s,%s,'instagram',%s,'video','Video',%s,%s,%s) RETURNING id''',
            (connection, account, str(uuid4()), video, state, version)).fetchone()['id']

    def idea(self, company, item):
        request_id = uuid4()
        with self.db.transaction():
            self.db.execute('''INSERT INTO idea_generation_requests(company_id,request_id,request_hash)
                VALUES (%s,%s,%s)''', (company, request_id, 'a'*64))
            idea = self.db.execute('''INSERT INTO ideas(company_id,title,concept,script,
                recommendation_version,model,evidence_schema_version,evidence_captured_at,
                request_id,request_hash,prior_idea_evidence)
                VALUES (%s,'Idea','Concept','Script',1,'test',1,now(),%s,%s,'[]') RETURNING id''',
                (company, request_id, 'a'*64)).fetchone()['id']
            self.db.execute('''INSERT INTO idea_sources(idea_id,library_item_id,source_order,
                analysis_version,analysis_payload,publication_context)
                VALUES (%s,%s,0,%s,'{}','{}')''', (idea, item, ANALYSIS_VERSION))
            self.db.execute('UPDATE ideas SET evidence_sealed=true WHERE id=%s', (idea,))
        return idea

    def test_authentication_and_new_user(self):
        for method, path in (('GET',''), ('POST','/welcome'), ('POST','/skip'), ('PUT','/company')):
            self.assertEqual(self.client.request(method, '/api/me/onboarding'+path).status_code, 401)
        state = self.state()
        self.assertEqual(state, {'company_id': None, 'welcome_seen': False, 'skipped': False,
            'progress': 0, 'complete': False, 'next_step': 'workspace',
            'steps': dict.fromkeys(('workspace','meta','account','analysis','idea'), False)})
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM user_onboarding_state').fetchone()['n'], 0)

    def test_welcome_skip_idempotent_and_independent(self):
        for path, field, column in (('/welcome','welcome_seen','welcome_seen_at'),
                                    ('/skip','skipped','onboarding_skipped_at')):
            first = self.request('POST','/api/me/onboarding'+path).json()
            timestamp = self.db.execute('SELECT '+column+' FROM user_onboarding_state WHERE user_id=%s',
                                        (USER_ID,)).fetchone()[column]
            second = self.request('POST','/api/me/onboarding'+path).json()
            self.assertEqual(first[field], True)
            self.assertEqual(second[field], True)
            self.assertEqual(self.db.execute('SELECT '+column+' FROM user_onboarding_state WHERE user_id=%s',
                                             (USER_ID,)).fetchone()[column], timestamp)
            self.assertEqual(second['progress'], 0)
            self.assertFalse(second['complete'])

    def test_membership_selection_archive_and_isolation(self):
        a = self.company()
        foreign = self.company(OTHER_USER_ID)
        self.assertEqual(self.state()['progress'], 20)
        self.assertEqual(self.state(user=OTHER_USER_ID)['company_id'], str(foreign))
        path = '/api/me/onboarding/company'
        self.assertEqual(self.request('PUT',path,json={'company_id':str(foreign)}).status_code,403)
        self.assertEqual(self.request('PUT',path,json={'company_id':str(uuid4())}).status_code,403)
        self.db.execute('UPDATE companies SET archived_at=now() WHERE id=%s',(a,))
        self.assertEqual(self.request('PUT',path,json={'company_id':str(a)}).status_code,403)
        self.assertEqual(self.state()['progress'],0)
        self.db.execute('UPDATE companies SET archived_at=NULL WHERE id=%s',(a,))
        self.assertEqual(self.request('PUT',path,json={'company_id':str(a)}).json()['company_id'],str(a))
        before = self.db.execute('SELECT updated_at FROM user_onboarding_state WHERE user_id=%s',(USER_ID,)).fetchone()['updated_at']
        self.assertEqual(self.request('PUT',path,json={'company_id':str(a)}).status_code,200)
        self.assertEqual(self.db.execute('SELECT updated_at FROM user_onboarding_state WHERE user_id=%s',(USER_ID,)).fetchone()['updated_at'],before)
        self.assertEqual(self.state(user=OTHER_USER_ID)['company_id'],str(foreign))

    def test_derivation_existing_user_and_meta_regression(self):
        company = self.company()
        connection = self.connection()
        account = self.link(company, connection, 'instagram')
        item = self.item(connection, account)
        self.idea(company, item)
        state = self.state()
        self.assertEqual(state['progress'],100)
        self.assertTrue(state['complete'])
        self.assertIsNone(state['next_step'])
        self.assertTrue(all(state['steps'].values()))
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM user_onboarding_state').fetchone()['n'],0)
        self.db.execute("UPDATE meta_connections SET status='disconnected',token_ciphertext=NULL WHERE id=%s",(connection,))
        state = self.state()
        self.assertEqual(state['progress'],80)
        self.assertEqual(state['next_step'],'meta')
        self.assertEqual(state['steps'], {'workspace':True,'meta':False,'account':True,
                                          'analysis':True,'idea':True})

    def test_meta_owner_and_organic_platforms(self):
        a = self.company()
        foreign = self.connection(OTHER_USER_ID)
        self.assertFalse(self.state()['steps']['meta'])
        owned = self.connection()
        self.assertEqual(self.state()['progress'],40)
        ads = self.link(a, owned, 'meta_ads')
        self.assertFalse(self.state()['steps']['account'])
        self.db.execute('DELETE FROM company_accounts WHERE account_id=%s',(ads,))
        self.link(a, owned, 'facebook')
        self.assertTrue(self.state()['steps']['account'])
        b = self.company()
        self.link(b, owned, 'instagram')
        self.assertEqual(self.request('PUT','/api/me/onboarding/company',json={'company_id':str(b)}).json()['steps']['account'],True)
        self.db.execute("UPDATE meta_connections SET status='reconnect_required' WHERE id=%s",(owned,))
        self.assertFalse(self.state()['steps']['meta'])
        self.assertNotEqual(foreign,owned)

    def test_analysis_states_and_versions(self):
        a = self.company()
        c = self.connection()
        account = self.link(a,c,'instagram')
        for state in ('queued','failed','unavailable','unsupported','processing'):
            self.item(c,account,state=state)
        self.item(c,account,version=ANALYSIS_VERSION+1)
        self.assertFalse(self.state()['steps']['analysis'])
        self.item(c,account)
        self.assertEqual(self.state()['next_step'],'idea')
        self.assertEqual(self.state()['progress'],80)

    def test_candidate_priority_stored_fallback_and_legacy(self):
        early = self.company()
        later = self.company()
        foreign = self.company(OTHER_USER_ID)
        self.db.execute('UPDATE companies SET created_at=now()-interval \'1 day\' WHERE id=%s',(early,))
        self.assertEqual(self.state()['company_id'],str(early))
        c = self.connection()
        self.link(later,c,'facebook')
        self.assertEqual(self.state()['company_id'],str(later))
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM user_onboarding_state').fetchone()['n'],0)
        self.request('PUT','/api/me/onboarding/company',json={'company_id':str(early)})
        self.assertEqual(self.state()['company_id'],str(early))
        self.db.execute('UPDATE companies SET archived_at=now() WHERE id=%s',(early,))
        self.assertEqual(self.state()['company_id'],str(later))
        self.db.execute('DELETE FROM company_memberships WHERE company_id=%s AND user_id=%s',(early,USER_ID))
        self.db.execute('DELETE FROM companies WHERE id=%s',(early,))
        self.assertIsNone(self.db.execute('SELECT onboarding_company_id FROM user_onboarding_state WHERE user_id=%s',(USER_ID,)).fetchone()['onboarding_company_id'])
        self.assertEqual(self.state()['company_id'],str(later))
        self.db.execute('DELETE FROM company_memberships WHERE company_id=%s AND user_id=%s',(later,USER_ID))
        self.assertIsNone(self.state()['company_id'])
        self.assertFalse(self.state()['steps']['workspace'])
        self.assertEqual(self.state(user=OTHER_USER_ID)['company_id'],str(foreign))
        # A legacy unclaimed company has no path through membership.
        legacy = self.db.execute("INSERT INTO companies(name) VALUES ('Legacy') RETURNING id").fetchone()['id']
        self.assertEqual(self.request('PUT','/api/me/onboarding/company',json={'company_id':str(legacy)}).status_code,403)

    def test_migration_rollback_and_rls(self):
        row = self.db.execute('''SELECT relrowsecurity FROM pg_class
            WHERE relnamespace=%s::regnamespace AND relname='user_onboarding_state' ''',
            (self.f.schema,)).fetchone()
        self.assertTrue(row['relrowsecurity'])
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM pg_policies WHERE schemaname=%s AND tablename='user_onboarding_state'",(self.f.schema,)).fetchone()['n'],0)
        with self.assertRaises(psycopg.errors.DuplicateTable):
            self.db.execute(self.f.migrations[12].read_text())
        self.db.execute('ROLLBACK')
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM pg_class WHERE relnamespace=%s::regnamespace AND relname='user_onboarding_state'",(self.f.schema,)).fetchone()['n'],1)
        reader = 'v7_reader_' + uuid4().hex
        self.f.admin.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(reader)))
        try:
            self.f.admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(self.f.schema),sql.Identifier(reader)))
            self.f.admin.execute(sql.SQL('GRANT SELECT,INSERT ON {}.user_onboarding_state TO {}').format(
                sql.Identifier(self.f.schema),sql.Identifier(reader)))
            auth_repository.ensure_profile(self.db, USER_ID)
            self.db.execute('INSERT INTO user_onboarding_state(user_id) VALUES (%s)',(USER_ID,))
            self.db.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(reader)))
            self.assertEqual(self.db.execute('SELECT count(*) AS n FROM user_onboarding_state').fetchone()['n'],0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.db.execute('INSERT INTO user_onboarding_state(user_id) VALUES (%s)',(OTHER_USER_ID,))
        finally:
            self.db.execute('RESET ROLE')
            self.f.admin.execute(sql.SQL('REVOKE ALL ON {}.user_onboarding_state FROM {}').format(
                sql.Identifier(self.f.schema),sql.Identifier(reader)))
            self.f.admin.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM {}').format(
                sql.Identifier(self.f.schema),sql.Identifier(reader)))
            self.f.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(reader)))

    def test_populated_v6_upgrade_preserves_rows(self):
        schema = 'v7_upgrade_' + uuid4().hex
        self.f.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={schema}')
            with psycopg.connect(url, autocommit=True, row_factory=dict_row) as db:
                for migration in self.f.migrations[:12]:
                    db.execute(migration.read_text())
                db.execute('INSERT INTO user_profiles(user_id) VALUES (%s)',(USER_ID,))
                company = db.execute("INSERT INTO companies(name) VALUES ('Existing') RETURNING id").fetchone()['id']
                db.execute("INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,'owner')",(company,USER_ID))
                db.execute(self.f.migrations[12].read_text())
                self.assertEqual(db.execute('SELECT count(*) AS n FROM company_memberships').fetchone()['n'],1)
                self.assertEqual(db.execute('SELECT count(*) AS n FROM user_onboarding_state').fetchone()['n'],0)
                db.execute('INSERT INTO user_onboarding_state(user_id,onboarding_company_id) VALUES (%s,%s)',(USER_ID,company))
                self.assertEqual(db.execute('SELECT onboarding_company_id FROM user_onboarding_state').fetchone()['onboarding_company_id'],company)
        finally:
            self.f.admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
