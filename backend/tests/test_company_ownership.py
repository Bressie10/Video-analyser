"""Real PostgreSQL tests of V3 ownership and populated V2 upgrades."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import company_ownership_repository as repo
from app import meta_library_repository as library
from app.meta import MetaNotConnected


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class CompanyOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.schema = 'company_test_' + uuid4().hex
        self.admin = psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True)
        self.admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={self.schema}')
        self.db = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self.addCleanup(self.db.close)
        self.migrations = sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql'))
        for path in self.migrations[:5]:
            self.db.execute(path.read_text())
        self.connection = self.new_connection('first')
        self.foreign_connection = self.new_connection('foreign')
        self.run = self.db.execute(
            "INSERT INTO meta_sync_runs(connection_id,kind) VALUES (%s,'sync') RETURNING id",
            (self.connection,),
        ).fetchone()['id']
        self.fb = self.account('facebook', 'fb')
        self.ig = self.account('instagram', 'ig')
        self.ads = self.account('meta_ads', 'ads')
        self.foreign_ads = self.account('meta_ads', 'foreign-ads', self.foreign_connection)
        self.organic = self.item(self.fb, 'organic', 'video', 'facebook')
        self.instagram = self.item(self.ig, 'instagram', 'reel', 'instagram')
        # Account and item platforms legitimately differ in V2.
        self.creative = self.item(self.ads, 'creative', 'video', 'facebook')
        self.ad_a = self.item(self.ads, 'a-secret', 'ad', 'meta_ads')
        self.ad_b = self.item(self.ads, 'b-secret', 'ad', 'meta_ads')
        self.unassigned = self.item(self.ads, 'unassigned-secret', 'ad', 'meta_ads')
        self.foreign_ad = self.item(self.foreign_ads, 'foreign-secret', 'ad', 'meta_ads', self.foreign_connection)
        for ad in (self.ad_a, self.ad_b, self.unassigned):
            self.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (ad, self.creative))
        self.video = self.db.execute(
            '''INSERT INTO videos(duration_seconds,container,file_size_bytes,meta_connection_id,transcript_text)
            VALUES (5,'mp4',100,%s,'Shared content') RETURNING id''', (self.connection,),
        ).fetchone()['id']
        self.db.execute('UPDATE meta_library_items SET video_id=%s WHERE id=%s', (self.video, self.creative))
        self.db.execute("INSERT INTO transcript_segments VALUES (%s,0,0,5,'Shared content')", (self.video,))
        self.db.execute('INSERT INTO scenes VALUES (%s,1,0,5,5,NULL)', (self.video,))
        self.db.execute(
            "INSERT INTO video_performance(video_id,source,view_count) VALUES (%s,'facebook',987654)",
            (self.video,),
        )
        self.db.execute(
            '''INSERT INTO meta_jobs(run_id,connection_id,item_id,kind,task_key)
            VALUES (%s,%s,%s,'analysis','retained')''', (self.run, self.connection, self.creative),
        )
        self.db.execute(
            "INSERT INTO meta_sessions VALUES ('retained-session',%s,now()+interval '1 day')", (self.connection,),
        )
        if not self._testMethodName.startswith('test_migration_'):
            self.migrate()
            self.a = repo.create_company(self.db, self.connection, 'A')['id']
            self.b = repo.create_company(self.db, self.connection, 'B')['id']
            self.foreign_company = repo.create_company(self.db, self.foreign_connection, 'Foreign')['id']

    def cleanup_schema(self):
        try:
            self.admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        finally:
            self.admin.close()

    def migrate(self):
        for migration in self.migrations[5:]:
            self.db.execute(migration.read_text())

    def new_connection(self, external):
        return self.db.execute(
            "INSERT INTO meta_connections(external_user_id,expires_at) VALUES (%s,now()+interval '1 day') RETURNING id",
            (external,),
        ).fetchone()['id']

    def account(self, platform, external, connection=None):
        return self.db.execute(
            '''INSERT INTO meta_accounts(connection_id,platform,external_id,label)
            VALUES (%s,%s,%s,%s) RETURNING id''',
            (connection or self.connection, platform, external, external),
        ).fetchone()['id']

    def item(self, account, external, kind, platform, connection=None):
        identity = self.db.execute(
            '''INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,content_type,label)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''',
            (connection or self.connection, account, platform, external, kind, external),
        ).fetchone()['id']
        self.db.execute('INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)',
                        (identity, Jsonb({'marker': external, 'impressions': 10})))
        return identity

    def link(self, company, account):
        repo.link_account(self.db, self.connection, company, account)

    def assign(self, company, ad):
        repo.assign_ad(self.db, self.connection, company, ad)

    def shared_setup(self):
        self.link(self.a, self.ads)
        self.link(self.b, self.ads)
        self.assign(self.a, self.ad_a)
        self.assign(self.b, self.ad_b)

    def ids(self, company):
        return {r['id'] for r in repo.list_items(self.db, self.connection, company)}

    def snapshot(self):
        tables = ('meta_connections', 'meta_sessions', 'meta_sync_runs', 'meta_accounts',
                  'meta_library_items', 'meta_ad_assets', 'meta_library_performance',
                  'meta_jobs', 'videos', 'video_performance', 'transcript_segments',
                  'scenes', 'on_screen_text', 'motion_events')
        return {table: self.db.execute(sql.SQL(
            'SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text'
        ).format(sql.Identifier(table))).fetchall() for table in tables}

    def assert_constraint(self, statement, params, error=psycopg.IntegrityError):
        with self.assertRaises(error):
            with self.db.transaction():
                self.db.execute(statement, params)

    def test_two_companies_and_exclusive_organic_accounts(self):
        self.assertEqual(len(repo.list_companies(self.db, self.connection)), 2)
        for account, platform in ((self.fb, 'facebook'), (self.ig, 'instagram')):
            self.link(self.a, account)
            self.link(self.a, account)
            with self.assertRaises(repo.OwnershipConflict):
                self.link(self.b, account)
            self.assert_constraint(
                '''INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
                VALUES (%s,%s,%s,%s)''', (self.b, self.connection, account, platform), psycopg.errors.UniqueViolation,
            )
        self.assertEqual(self.ids(self.a), {self.organic, self.instagram})
        self.assertEqual(self.ids(self.b), set())
        self.assertEqual(repo.performance(self.db, self.connection, self.a, self.organic)[0]['item_id'], self.organic)

    def test_shared_ads_account_grants_nothing_without_assignment(self):
        self.link(self.a, self.ads)
        self.link(self.b, self.ads)
        self.assertEqual(self.ids(self.a), set())
        self.assertEqual(self.ids(self.b), set())
        self.assign(self.a, self.ad_a)
        self.assign(self.a, self.ad_a)
        with self.assertRaises(repo.OwnershipConflict):
            self.assign(self.b, self.ad_a)
        self.assert_constraint(
            '''INSERT INTO company_ad_assignments(ad_item_id,company_id,connection_id,account_id)
            VALUES (%s,%s,%s,%s)''', (self.ad_a, self.b, self.connection, self.ads), psycopg.errors.UniqueViolation,
        )
        self.assertEqual(self.ids(self.a), {self.ad_a, self.creative})
        for reader in (repo.get_item, repo.performance, repo.analysis, repo.ad_assets):
            with self.assertRaises(repo.OwnershipNotFound):
                reader(self.db, self.connection, self.a, self.unassigned)

    def test_shared_creative_does_not_leak_ad_metadata_or_performance(self):
        self.shared_setup()
        self.db.execute(
            "UPDATE meta_library_items SET label='b-secret',analysis_error='b-secret',metrics_error='b-secret' WHERE id=%s",
            (self.creative,),
        )
        for company, own, other in ((self.a, self.ad_a, self.ad_b), (self.b, self.ad_b, self.ad_a)):
            self.assertEqual(self.ids(company), {own, self.creative})
            self.assertEqual([r['item_id'] for r in repo.performance(self.db, self.connection, company, self.creative)], [own])
            self.assertEqual([r['item_id'] for r in repo.performance(self.db, self.connection, company, own)], [own])
            assets = repo.ad_assets(self.db, self.connection, company, own)
            self.assertEqual([r['id'] for r in assets], [self.creative])
            for key in ('label', 'account_id', 'analysis_error', 'metrics_error', 'metrics_state'):
                self.assertNotIn(key, assets[0])
            with self.assertRaises(repo.OwnershipNotFound):
                repo.get_item(self.db, self.connection, company, other)
            content = repo.analysis(self.db, self.connection, company, self.creative)
            self.assertEqual(content['video']['id'], self.video)
            self.assertNotEqual(self.video, self.creative)
            self.assertEqual(content['transcript_segments'][0]['text'], 'Shared content')
            self.assertNotIn('987654', str(content))
            self.assertNotIn('performance', str(content))
        self.assertEqual({r['item_id'] for r in library.public_performance(self.db, self.creative)},
                         {self.creative, self.ad_a, self.ad_b, self.unassigned})

    def test_creative_access_does_not_grant_organic_metrics_or_sibling_ads(self):
        self.shared_setup()
        self.link(self.a, self.fb)
        self.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.ad_b, self.organic))
        self.assertIn(self.organic, self.ids(self.b))
        self.assertEqual([r['item_id'] for r in repo.performance(self.db, self.connection, self.b, self.organic)], [self.ad_b])
        self.assertEqual([r['item_id'] for r in repo.performance(self.db, self.connection, self.a, self.organic)], [self.organic])
        self.assertNotIn(self.ad_b, self.ids(self.a))

    def test_foreign_company_and_resources_rejected(self):
        for company in (self.foreign_company, uuid4()):
            for operation, extra in (
                (repo.get_company, ()), (repo.list_items, ()), (repo.get_item, (self.organic,)),
                (repo.performance, (self.organic,)), (repo.analysis, (self.creative,)), (repo.ad_assets, (self.ad_a,)),
                (repo.link_account, (self.fb,)), (repo.unlink_account, (self.fb,)),
                (repo.assign_ad, (self.ad_a,)), (repo.unassign_ad, (self.ad_a,)), (repo.set_company_archived, ()),
            ):
                with self.assertRaises(repo.CompanyNotFound):
                    operation(self.db, self.connection, company, *extra)
        with self.assertRaises(repo.OwnershipNotFound):
            self.link(self.a, self.foreign_ads)
        with self.assertRaises(repo.OwnershipNotFound):
            self.assign(self.a, self.foreign_ad)
        with self.assertRaises(repo.CompanyNotFound):
            repo.reassign_organic_account(self.db, self.connection, self.a, self.foreign_company, self.fb)

    def test_ad_assignment_requires_correct_account_link_and_item_type(self):
        with self.assertRaises(repo.OwnershipConflict):
            self.assign(self.a, self.ad_a)
        self.link(self.a, self.ads)
        with self.assertRaises(repo.OwnershipNotFound):
            self.assign(self.a, self.creative)
        self.assert_constraint(
            '''INSERT INTO company_ad_assignments(ad_item_id,company_id,connection_id,account_id)
            VALUES (%s,%s,%s,%s)''', (self.creative, self.a, self.connection, self.ads),
        )
        for company, account in ((self.a, self.fb), (self.a, self.foreign_ads), (self.foreign_company, self.ads)):
            self.assert_constraint(
                '''INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
                VALUES (%s,%s,%s,'meta_ads')''', (company, self.connection, account),
            )

    def test_unlink_and_explicit_reassignment(self):
        self.link(self.a, self.fb)
        repo.reassign_organic_account(self.db, self.connection, self.a, self.b, self.fb)
        self.assertNotIn(self.organic, self.ids(self.a))
        self.assertIn(self.organic, self.ids(self.b))
        repo.unlink_account(self.db, self.connection, self.b, self.fb)
        self.assertNotIn(self.organic, self.ids(self.b))
        self.shared_setup()
        with self.assertRaises(repo.OwnershipConflict):
            repo.unlink_account(self.db, self.connection, self.a, self.ads)
        self.assert_constraint('DELETE FROM company_accounts WHERE company_id=%s AND account_id=%s', (self.a, self.ads))
        repo.reassign_ad(self.db, self.connection, self.a, self.b, self.ad_a)
        self.assertEqual(self.ids(self.a), set())
        self.assertIn(self.ad_a, self.ids(self.b))
        repo.unlink_account(self.db, self.connection, self.a, self.ads)
        repo.unassign_ad(self.db, self.connection, self.a, self.ad_b)
        self.assertIn(self.ad_b, self.ids(self.b))
        repo.unassign_ad(self.db, self.connection, self.b, self.ad_a)
        self.assertNotIn(self.ad_a, self.ids(self.b))
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM meta_library_items WHERE id=%s', (self.ad_a,)).fetchone())

    def test_failed_reassignment_is_atomic(self):
        self.link(self.a, self.ads)
        self.assign(self.a, self.ad_a)
        with self.assertRaises(repo.OwnershipConflict):
            repo.reassign_ad(self.db, self.connection, self.a, self.b, self.ad_a)
        self.assertIn(self.ad_a, self.ids(self.a))
        with self.assertRaises(repo.CompanyNotFound):
            repo.reassign_ad(self.db, self.connection, self.a, self.foreign_company, self.ad_a)
        self.assertIn(self.ad_a, self.ids(self.a))

    def test_archive_retains_ownership_disables_access_and_allows_release(self):
        self.shared_setup()
        self.link(self.a, self.fb)
        repo.set_company_archived(self.db, self.connection, self.a)
        self.assertEqual([r['id'] for r in repo.list_companies(self.db, self.connection)], [self.b])
        self.assertEqual(len(repo.list_companies(self.db, self.connection, include_archived=True)), 2)
        for reader, extra in ((repo.list_items, ()), (repo.get_item, (self.ad_a,)), (repo.performance, (self.creative,)),
                              (repo.analysis, (self.creative,)), (repo.ad_assets, (self.ad_a,)),
                              (repo.assign_ad, (self.unassigned,)), (repo.link_account, (self.ig,))):
            with self.assertRaises(repo.CompanyNotFound):
                reader(self.db, self.connection, self.a, *extra)
        with self.assertRaises(repo.OwnershipConflict):
            self.link(self.b, self.fb)
        with self.assertRaises(repo.OwnershipConflict):
            self.assign(self.b, self.ad_a)
        repo.set_company_archived(self.db, self.connection, self.a, archived=False)
        self.assertIn(self.ad_a, self.ids(self.a))
        repo.set_company_archived(self.db, self.connection, self.a)
        repo.reassign_ad(self.db, self.connection, self.a, self.b, self.ad_a)
        repo.reassign_organic_account(self.db, self.connection, self.a, self.b, self.fb)
        repo.unlink_account(self.db, self.connection, self.a, self.ads)
        self.assertIsNotNone(repo.get_company(self.db, self.connection, self.a)['archived_at'])
        self.assertIn(self.organic, self.ids(self.b))

    def test_disconnect_preserves_company_and_meta_data(self):
        self.shared_setup()
        before = self.snapshot()
        owners = self.db.execute('SELECT * FROM company_ad_assignments ORDER BY ad_item_id').fetchall()
        links = self.db.execute('SELECT * FROM company_accounts ORDER BY company_id,account_id').fetchall()
        companies = repo.list_companies(self.db, self.connection)
        with patch.dict(os.environ, {'DATABASE_URL': self.url}):
            library.disconnect(self.connection)
            with self.assertRaises(MetaNotConnected):
                library.session_connection('retained-session')
        self.assertEqual(repo.list_companies(self.db, self.connection), companies)
        self.assertEqual(self.db.execute('SELECT * FROM company_ad_assignments ORDER BY ad_item_id').fetchall(), owners)
        self.assertEqual(self.db.execute('SELECT * FROM company_accounts ORDER BY company_id,account_id').fetchall(), links)
        after = self.snapshot()
        for table in before.keys() - {'meta_connections', 'meta_sessions', 'meta_sync_runs', 'meta_jobs'}:
            self.assertEqual(after[table], before[table], table)
        for table in ('meta_jobs', 'meta_sync_runs'):
            self.assertEqual(len(after[table]), len(before[table]))
        self.assert_constraint('DELETE FROM meta_connections WHERE id=%s', (self.connection,))

    def test_cross_connection_creative_edges_fail_closed(self):
        self.shared_setup()
        foreign_asset = self.item(self.foreign_ads, 'foreign-asset', 'video', 'facebook', self.foreign_connection)
        self.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.ad_a, foreign_asset))
        self.db.execute('INSERT INTO meta_ad_assets VALUES (%s,%s)', (self.foreign_ad, self.creative))
        self.assertNotIn(foreign_asset, self.ids(self.a))
        self.assertEqual([r['id'] for r in repo.ad_assets(self.db, self.connection, self.a, self.ad_a)], [self.creative])
        metrics = repo.performance(self.db, self.connection, self.a, self.creative)
        self.assertEqual([r['item_id'] for r in metrics], [self.ad_a])
        self.assertEqual(metrics[0]['attribution'], 'ad')

    def test_new_cross_connection_writes_and_parent_changes_rejected(self):
        for statement, params in (
            ('UPDATE meta_library_items SET account_id=%s WHERE id=%s', (self.foreign_ads, self.creative)),
            ('UPDATE videos SET meta_connection_id=%s WHERE id=%s', (self.foreign_connection, self.video)),
            ('UPDATE meta_accounts SET connection_id=%s WHERE id=%s', (self.foreign_connection, self.ads)),
            ('UPDATE meta_jobs SET connection_id=%s WHERE item_id=%s', (self.foreign_connection, self.creative)),
            ('UPDATE meta_accounts SET initial_run_id=%s WHERE id=%s', (self.run, self.foreign_ads)),
        ):
            self.assert_constraint(statement, params)
        self.shared_setup()
        self.assert_constraint("UPDATE meta_library_items SET content_type='video' WHERE id=%s", (self.ad_a,))
        self.assert_constraint('DELETE FROM meta_library_items WHERE id=%s', (self.ad_a,))
        self.assert_constraint('UPDATE companies SET connection_id=%s WHERE id=%s', (self.foreign_connection, self.a))

    def race(self, operation):
        barrier = Barrier(2)
        def attempt(company):
            with psycopg.connect(self.url, autocommit=True, row_factory=dict_row) as db:
                db.execute("SET lock_timeout='5s'")
                barrier.wait(timeout=5)
                try:
                    operation(db, self.connection, company)
                    return 'assigned'
                except repo.OwnershipConflict:
                    return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(attempt, (self.a, self.b))), ['assigned', 'conflict'])

    def test_concurrent_organic_claims(self):
        self.race(lambda db, connection, company: repo.link_account(db, connection, company, self.fb))

    def test_concurrent_ad_assignments(self):
        self.link(self.a, self.ads)
        self.link(self.b, self.ads)
        self.race(lambda db, connection, company: repo.assign_ad(db, connection, company, self.ad_a))

    def test_migration_preserves_populated_v2_and_leaves_everything_unassigned(self):
        before = self.snapshot()
        self.migrate()
        self.assertEqual(self.snapshot(), before)
        for table in ('companies', 'company_accounts', 'company_ad_assignments'):
            self.assertEqual(self.db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n'], 0)
        company = repo.create_company(self.db, self.connection, 'Manual')['id']
        self.assertEqual(repo.list_items(self.db, self.connection, company), [])
        constraints = self.db.execute(
            "SELECT conname,convalidated FROM pg_constraint WHERE connamespace=%s::regnamespace AND conname LIKE 'meta_%%connection_fk'",
            (self.schema,),
        ).fetchall()
        self.assertEqual(len(constraints), 5)
        self.assertTrue(all(not r['convalidated'] for r in constraints))

    def test_migration_preserves_inconsistent_v2_rows_but_reads_fail_closed(self):
        self.db.execute('UPDATE meta_library_items SET account_id=%s WHERE id=%s', (self.foreign_ads, self.organic))
        self.db.execute('UPDATE videos SET meta_connection_id=%s WHERE id=%s', (self.foreign_connection, self.video))
        self.db.execute('UPDATE meta_jobs SET connection_id=%s', (self.foreign_connection,))
        self.db.execute('UPDATE meta_accounts SET initial_run_id=%s WHERE id=%s', (self.run, self.foreign_ads))
        before = self.snapshot()
        self.migrate()
        self.assertEqual(self.snapshot(), before)
        self.a = repo.create_company(self.db, self.connection, 'Manual')['id']
        self.link(self.a, self.fb)
        self.link(self.a, self.ads)
        self.assign(self.a, self.ad_a)
        self.assertNotIn(self.organic, self.ids(self.a))
        self.assertIsNone(repo.analysis(self.db, self.connection, self.a, self.creative))
        self.assertIsNone(repo.get_item(self.db, self.connection, self.a, self.creative)['video_id'])

    def test_migration_failure_rolls_back_all_schema_changes(self):
        self.db.execute('CREATE TABLE company_accounts (sentinel INTEGER)')
        before = self.snapshot()
        with self.assertRaises(psycopg.errors.DuplicateTable):
            self.migrate()
        self.db.execute('ROLLBACK')
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.db.execute("SELECT to_regclass('companies') AS name").fetchone()['name'])
        self.assertIsNone(self.db.execute(
            "SELECT conname FROM pg_constraint WHERE connamespace=%s::regnamespace AND conname='meta_accounts_ownership_key'",
            (self.schema,),
        ).fetchone())


if __name__ == '__main__':
    unittest.main()
