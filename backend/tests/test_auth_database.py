"""Fresh + populated 001–011 PostgreSQL migrations and authenticated API contract."""
import os
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from app import auth_repository as repo
from app.auth import get_token_verifier
from app.auth_routes import router
from app.auth_dependencies import require_company_access, require_company_role
from auth_fixtures import LocalAuth, USER_ID, OTHER_USER_ID


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class AuthDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'auth_test_' + uuid4().hex
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={self.schema}')
        self.db = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self.addCleanup(self.db.close)
        self.migrations = sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql'))
        for path in self.migrations[:10]:
            self.db.execute(path.read_text())
        if self._testMethodName not in ('test_populated_v5_upgrade', 'test_migration_failure_is_transactional'):
            self.db.execute(self.migrations[10].read_text())
        self.auth = LocalAuth()
        transport = self.auth.serve_jwks()
        transport.start()
        self.addCleanup(transport.stop)
        env = patch.dict(os.environ, {'DATABASE_URL': self.url})
        env.start()
        self.addCleanup(env.stop)
        app = FastAPI()
        app.include_router(router)
        @app.get('/companies/{company_id}/access')
        def access(company=Depends(require_company_access)):
            return {'id': company['id']}
        @app.get('/companies/{company_id}/owner')
        def owner(company=Depends(require_company_role())):
            return {'id': company['id']}
        app.dependency_overrides[get_token_verifier] = lambda: self.auth.verifier
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def cleanup_schema(self):
        try:
            self.admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        finally:
            self.admin.close()

    def get(self, path, user=USER_ID):
        return self.client.get(path, headers={'Authorization': 'Bearer '+self.auth.token(sub=str(user))})

    def create(self, user=USER_ID, name='Workspace'):
        return repo.create_company_for_user(self.db, user, name)['id']

    def test_fresh_schema_company_creation_and_membership(self):
        company = self.create()
        self.assertIsNone(self.db.execute('SELECT * FROM companies WHERE id=%s', (company,)).fetchone()['connection_id'])
        self.assertEqual(repo.require_company_role(self.db, USER_ID, company)['role'], 'owner')
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM company_memberships').fetchone()['n'], 1)

    def test_membership_matrix_and_missing_company(self):
        company = self.create()
        repo.ensure_profile(self.db, OTHER_USER_ID)
        self.db.execute("INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,'member')", (company, OTHER_USER_ID))
        for user in (USER_ID, OTHER_USER_ID):
            self.assertEqual(self.get(f'/companies/{company}/access', user).status_code, 200)
        self.assertEqual(self.get(f'/companies/{company}/owner').status_code, 200)
        self.assertEqual(self.get(f'/companies/{company}/owner', OTHER_USER_ID).status_code, 403)
        self.assertEqual(self.get(f'/companies/{company}/access', uuid4()).status_code, 403)
        self.assertEqual(self.get(f'/companies/{uuid4()}/access').status_code, 403)
        self.assertEqual(self.client.get(f'/companies/{company}/access').status_code, 401)

    def test_archived_company(self):
        company = self.create()
        self.db.execute('UPDATE companies SET archived_at=now() WHERE id=%s', (company,))
        self.assertEqual(self.get(f'/companies/{company}/access').status_code, 403)
        self.assertEqual(self.get('/api/me/companies').json(), {'companies': []})
        self.assertEqual(len(self.get('/api/me/companies?include_archived=true').json()['companies']), 1)
        self.assertEqual(repo.require_company_role(self.db, USER_ID, company, include_archived=True)['role'], 'owner')
        with self.assertRaises(repo.CompanyAccessDenied):
            repo.require_company_access(self.db, OTHER_USER_ID, company, include_archived=True)

    def test_me_lazy_profile_and_safe_contract(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        for _ in range(2):
            response = self.get('/api/me?user_id='+str(OTHER_USER_ID))
            self.assertEqual(response.json(), {'user_id': str(USER_ID), 'email': 'example@example.test', 'profile': {'display_name': None}})
            self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM user_profiles').fetchone()['n'], 1)

    def test_lists_only_memberships_and_multiple_companies(self):
        a, b = self.create(), self.create(name='Second')
        foreign = self.create(OTHER_USER_ID)
        response = self.get('/api/me/companies')
        self.assertEqual({c['id'] for c in response.json()['companies']}, {str(a), str(b)})
        self.assertNotIn(str(foreign), response.text)
        self.assertNotIn('connection_id', response.text)
        self.assertEqual(self.client.get('/api/me/companies').status_code, 401)

    def test_creation_failure_rolls_back_even_when_caught(self):
        self.db.execute("""CREATE FUNCTION reject_membership() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced membership failure'; END; $$;
            CREATE TRIGGER reject_membership BEFORE INSERT ON company_memberships
            FOR EACH ROW EXECUTE FUNCTION reject_membership()""")
        with self.db.transaction():
            with self.assertRaises(psycopg.Error):
                self.create()
            for table in ('companies', 'company_memberships', 'user_profiles'):
                self.assertEqual(self.db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n'], 0)

    def test_membership_fk_roles_and_uniqueness(self):
        company = self.create()
        for statement, params in (
            ("INSERT INTO company_memberships VALUES (%s,%s,'admin',now())", (company, USER_ID)),
            ("INSERT INTO company_memberships VALUES (%s,%s,'owner',now())", (company, USER_ID)),
            ("INSERT INTO company_memberships VALUES (%s,%s,'member',now())", (company, uuid4())),
            ("INSERT INTO company_memberships VALUES (%s,%s,'member',now())", (uuid4(), USER_ID)),
        ):
            with self.assertRaises(psycopg.IntegrityError), self.db.transaction():
                self.db.execute(statement, params)

    def test_authorization_locks_membership_and_company(self):
        company = self.create()
        with self.db.transaction():
            repo.require_company_access(self.db, USER_ID, company)
            with psycopg.connect(self.url, autocommit=True) as other:
                other.execute("SET lock_timeout='50ms'")
                for statement in ('DELETE FROM company_memberships WHERE company_id=%s', 'UPDATE companies SET archived_at=now() WHERE id=%s'):
                    with self.assertRaises(psycopg.errors.LockNotAvailable):
                        other.execute(statement, (company,))

    def test_owned_meta_connection_never_claims_legacy(self):
        legacy = self.db.execute("INSERT INTO meta_connections(external_user_id,expires_at) VALUES ('legacy',now()+interval '1 day') RETURNING id,expires_at").fetchone()
        with self.assertRaises(repo.CompanyAccessDenied):
            repo.require_owned_meta_connection(self.db, USER_ID, legacy['id'])
        with self.assertRaises(psycopg.errors.UniqueViolation):
            repo.create_owned_meta_connection(self.db, USER_ID, 'legacy', 'ciphertext', legacy['expires_at'])
        self.assertIsNone(self.db.execute('SELECT owner_user_id FROM meta_connections WHERE id=%s', (legacy['id'],)).fetchone()['owner_user_id'])
        owned = repo.create_owned_meta_connection(self.db, USER_ID, 'new', 'ciphertext', legacy['expires_at'])
        self.assertEqual(repo.require_owned_meta_connection(self.db, USER_ID, owned['id'])['id'], owned['id'])
        with self.assertRaises(repo.CompanyAccessDenied):
            repo.require_owned_meta_connection(self.db, OTHER_USER_ID, owned['id'])

    def test_populated_v5_upgrade(self):
        connection = self.db.execute("INSERT INTO meta_connections(external_user_id,expires_at) VALUES ('legacy',now()+interval '1 day') RETURNING id").fetchone()['id']
        company = self.db.execute("INSERT INTO companies(connection_id,name) VALUES (%s,'Legacy') RETURNING id", (connection,)).fetchone()['id']
        account = self.db.execute("INSERT INTO meta_accounts(connection_id,platform,external_id,label) VALUES (%s,'facebook','page','Page') RETURNING id", (connection,)).fetchone()['id']
        self.db.execute("INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform) VALUES (%s,%s,%s,'facebook')", (company, connection, account))
        self.db.execute("INSERT INTO meta_sessions VALUES ('session-hash',%s,now()+interval '1 day')", (connection,))
        self.db.execute("INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,content_type,label) VALUES (%s,%s,'facebook','post','video','Video')", (connection, account))
        video = self.db.execute("INSERT INTO videos(duration_seconds,container,file_size_bytes,meta_connection_id,transcript_text) VALUES (5,'mp4',100,%s,'Legacy analysis') RETURNING id", (connection,)).fetchone()['id']
        self.db.execute("INSERT INTO transcript_segments VALUES (%s,0,0,5,'Legacy analysis')", (video,))
        self.db.execute("UPDATE meta_library_items SET video_id=%s,analysis_state='completed',analysis_version=1", (video,))
        item = self.db.execute('SELECT id FROM meta_library_items').fetchone()['id']
        ads = self.db.execute("INSERT INTO meta_accounts(connection_id,platform,external_id,label) VALUES (%s,'meta_ads','ads','Ads') RETURNING id", (connection,)).fetchone()['id']
        self.db.execute("INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform) VALUES (%s,%s,%s,'meta_ads')", (company, connection, ads))
        ad = self.db.execute("INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,content_type,label) VALUES (%s,%s,'meta_ads','ad','ad','Ad') RETURNING id", (connection, ads)).fetchone()['id']
        self.db.execute('INSERT INTO company_ad_assignments(ad_item_id,company_id,connection_id,account_id) VALUES (%s,%s,%s,%s)', (ad, company, connection, ads))
        profile = self.db.execute("INSERT INTO company_profiles(company_id,scope,generator_version,schema_version) VALUES (%s,'shared','v1','v1') RETURNING id", (company,)).fetchone()['id']
        revision = self.db.execute("""INSERT INTO company_profile_revisions(profile_id,revision_number,input_revision,input_hash,assignment_version,generator_version,schema_version,model,document,evidence_manifest)
            VALUES (%s,1,1,'legacy','v1','v1','v1','test','{}','{}') RETURNING id""", (profile,)).fetchone()['id']
        self.db.execute('UPDATE company_profiles SET current_revision_id=%s WHERE id=%s', (revision, profile))
        request_id = uuid4()
        with self.db.transaction():
            self.db.execute("INSERT INTO idea_generation_requests(company_id,request_id,request_hash) VALUES (%s,%s,%s)", (company, request_id, 'a'*64))
            idea = self.db.execute("""INSERT INTO ideas(company_id,title,concept,script,recommendation_version,model,evidence_schema_version,evidence_captured_at,request_id,request_hash,prior_idea_evidence,status,feedback)
                VALUES (%s,'Legacy idea','Concept','Script',1,'test',1,now(),%s,%s,'[]','published','liked') RETURNING id""", (company, request_id, 'a'*64)).fetchone()['id']
            self.db.execute("INSERT INTO idea_sources VALUES (%s,%s,0,1,'{}','{}')", (idea, item))
            self.db.execute("INSERT INTO idea_target_platforms VALUES (%s,'facebook')", (idea,))
            self.db.execute('UPDATE ideas SET evidence_sealed=true WHERE id=%s', (idea,))
            self.db.execute('INSERT INTO idea_publications(idea_id,library_item_id) VALUES (%s,%s)', (idea, item))
        tables = ('meta_connections', 'companies', 'meta_accounts', 'company_accounts',
                  'meta_sessions', 'meta_library_items', 'videos', 'transcript_segments',
                  'company_ad_assignments', 'company_profiles', 'company_profile_revisions',
                  'idea_generation_requests', 'ideas', 'idea_sources', 'idea_target_platforms',
                  'idea_publications')
        before = {t: self.db.execute(sql.SQL('SELECT * FROM {} ORDER BY 1').format(sql.Identifier(t))).fetchall() for t in tables}
        self.db.execute(self.migrations[10].read_text())
        for table in tables:
            after = self.db.execute(sql.SQL('SELECT * FROM {} ORDER BY 1').format(sql.Identifier(table))).fetchall()
            if table == 'meta_connections':
                self.assertIsNone(after[0].pop('owner_user_id'))
            self.assertEqual(after, before[table])
        self.assertEqual(self.get('/api/me/companies').json(), {'companies': []})
        self.assertEqual(self.get(f'/companies/{company}/access').status_code, 403)
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM company_memberships').fetchone()['n'], 0)
        new = self.create()
        account = self.db.execute("INSERT INTO meta_accounts(connection_id,platform,external_id,label) VALUES (%s,'facebook','unlinked','Unlinked') RETURNING id", (connection,)).fetchone()['id']
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.db.transaction():
            self.db.execute("INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform) VALUES (%s,%s,%s,'facebook')", (new, connection, account))

    def test_new_tables_rls_default_deny(self):
        rows = self.db.execute("SELECT relname,relrowsecurity FROM pg_class WHERE relnamespace=%s::regnamespace AND relname IN ('user_profiles','company_memberships')", (self.schema,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['relrowsecurity'] for row in rows))
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM pg_policies WHERE schemaname=%s', (self.schema,)).fetchone()['n'], 0)

    def test_migration_failure_is_transactional(self):
        self.db.execute('CREATE TABLE company_memberships(sentinel INTEGER)')
        with self.assertRaises(psycopg.errors.DuplicateTable):
            self.db.execute(self.migrations[10].read_text())
        self.db.execute('ROLLBACK')
        self.assertIsNone(self.db.execute("SELECT to_regclass('user_profiles') AS name").fetchone()['name'])
        self.assertEqual(self.db.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema=%s AND table_name='companies' AND column_name='connection_id'", (self.schema,)).fetchone()['is_nullable'], 'NO')
        self.assertIsNone(self.db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name='meta_connections' AND column_name='owner_user_id'", (self.schema,)).fetchone())

    def test_profile_commit_failure_is_not_success(self):
        @contextmanager
        def failing_commit():
            yield object()
            raise psycopg.OperationalError('private connection details')
        with patch('app.auth_dependencies.database', failing_commit), patch.object(repo, 'ensure_profile', return_value={'display_name': None}):
            response = self.get('/api/me')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Application data is unavailable.'})
        self.assertNotIn('private connection details', response.text)
