"""009 API -> real ownership -> PostgreSQL, with stubbed idea/profile generators."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app import company_ownership_repository as ownership
from app import idea_repository as ideas
from app import meta_library_repository as library
from app import meta
import test_idea_integration as integration


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class IdeaFeedbackPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration.IdeaIntegrationTests('test_real_adapter_shared_creative_and_profile_revisions')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.f = self.fixture.f
        self.client = self.fixture.client
        self.body = {'request_id': str(uuid4()), 'target_platforms': ['facebook'], 'video_ids': [str(self.f.creative)]}
        self.saved = self.fixture.generate(body=self.body)
        self.id = self.saved['id']
        self.base = f'/api/meta/companies/{self.f.a}/ideas/{self.id}'
        self.original_evidence = self.client.get(self.base + '/evidence').json()

    def status(self, value):
        return self.client.patch(self.base, json={'status': value})

    def feedback(self, value, **kwargs):
        return self.client.put(self.base + '/feedback', json={'feedback': value, **kwargs})

    def publication_url(self, item):
        return self.base + f'/publications/{item}'

    def link(self, item):
        return self.client.put(self.publication_url(item))

    def assert_ok(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_draft_to_used(self):
        self.assertEqual(self.saved['status'], 'draft')
        self.assertEqual(self.assert_ok(self.status('used'))['status'], 'used')

    def test_publish_from_draft_and_used(self):
        self.assertEqual(self.assert_ok(self.status('published'))['status'], 'published')
        self.assert_ok(self.status('used'))
        self.assertEqual(self.assert_ok(self.status('published'))['status'], 'published')

    def test_discard_and_restore_draft(self):
        self.assertEqual(self.assert_ok(self.status('discarded'))['status'], 'discarded')
        self.assertEqual(self.assert_ok(self.status('draft'))['status'], 'draft')

    def test_invalid_lifecycle_rejected_without_change(self):
        for value in ('scheduled', '', None, 1, ['used']):
            with self.subTest(value=value):
                self.assertEqual(self.status(value).status_code, 422)
        self.assertEqual(self.client.get(self.base).json()['status'], 'draft')

    def test_liked_feedback(self):
        self.assertEqual(self.saved['feedback'], 'none')
        row = self.assert_ok(self.feedback('liked'))
        self.assertEqual(row['feedback'], 'liked')
        self.assertIsNone(row['feedback_reason'])

    def test_disliked_with_reason(self):
        row = self.assert_ok(self.feedback('disliked', reason='  Too repetitive  '))
        self.assertEqual(row['feedback'], 'disliked')
        self.assertEqual(row['feedback_reason'], 'Too repetitive')

    def test_disliked_without_reason(self):
        for body in ({}, {'reason': None}, {'reason': ''}, {'reason': '  '}):
            row = self.assert_ok(self.feedback('disliked', **body))
            self.assertEqual(row['feedback'], 'disliked')
            self.assertIsNone(row['feedback_reason'])

    def test_feedback_is_current_state_and_clears_old_reason(self):
        self.assert_ok(self.feedback('disliked', reason='Old reason'))
        self.assertIsNone(self.assert_ok(self.feedback('liked'))['feedback_reason'])
        self.assert_ok(self.feedback('disliked', reason='Another reason'))
        row = self.assert_ok(self.feedback('none'))
        self.assertEqual(row['feedback'], 'none')
        self.assertIsNone(row['feedback_reason'])
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM ideas').fetchone()['n'], 1)

    def test_invalid_feedback_rejected(self):
        for body in ({}, {'feedback': 'loved'}, {'feedback': None},
                     {'feedback': 'liked', 'reason': 'Not allowed'},
                     {'feedback': 'none', 'reason': 'Not allowed'},
                     {'feedback': 'disliked', 'reason': 'x' * 2001},
                     {'feedback': 'liked', 'company_id': str(self.f.b)}):
            self.assertEqual(self.client.put(self.base + '/feedback', json=body).status_code, 422)

    def test_foreign_company_cannot_mutate_or_read_idea(self):
        for company in (self.f.b, self.f.foreign_company, uuid4()):
            base = f'/api/meta/companies/{company}/ideas/{self.id}'
            for response in (self.client.patch(base, json={'status': 'used'}),
                             self.client.put(base + '/feedback', json={'feedback': 'liked'}),
                             self.client.put(base + f'/publications/{self.f.organic}'),
                             self.client.delete(base + f'/publications/{self.f.organic}'),
                             self.client.get(base)):
                self.assertEqual(response.status_code, 404 if company == self.f.b else 403, response.text)
        self.assertEqual(self.client.get(self.base).json(), self.saved)

    def test_signed_out_and_unrelated_user_fail_closed(self):
        self.client.headers.pop('Authorization')
        self.assertEqual(self.status('used').status_code, 401)
        self.assertEqual(self.feedback('liked').status_code, 401)
        self.assertEqual(self.link(self.f.organic).status_code, 401)
        self.f.db.execute("INSERT INTO meta_sessions VALUES (%s,%s,now()+interval '1 day')",
                          (library.token_hash('foreign-session'), self.f.foreign_connection))
        self.client.headers['Authorization'] = 'Bearer ' + self.fixture.fixture.auth.token(sub=str(uuid4()))
        self.assertEqual(self.status('used').status_code, 403)
        self.assertEqual(self.feedback('liked').status_code, 403)
        self.assertEqual(self.link(self.f.organic).status_code, 403)

    def test_multiple_publications_and_duplicate_idempotency(self):
        first = self.assert_ok(self.link(self.f.organic))
        self.assertEqual(first['status'], 'draft')  # No implicit lifecycle transition.
        self.assertEqual(first, self.assert_ok(self.link(self.f.organic)))
        second = self.assert_ok(self.link(self.f.instagram))
        self.assertEqual({p['library_item_id'] for p in second['publications']},
                         {str(self.f.organic), str(self.f.instagram)})
        self.assertEqual(second, self.client.get(self.base).json())

    def test_foreign_unowned_and_missing_items_cannot_be_linked(self):
        for identity in (self.fixture.fixture.b_facebook, self.f.unassigned, self.f.foreign_ad, uuid4()):
            self.assertEqual(self.link(identity).status_code, 404)
        self.assertEqual(self.client.get(self.base).json()['publications'], [])

    def test_shared_creative_does_not_authorize_sibling_ad(self):
        self.assert_ok(self.link(self.f.creative))
        self.assertEqual(self.link(self.f.ad_b).status_code, 404)
        self.assert_ok(self.link(self.f.ad_a))

    def test_publication_survives_organic_unlink_without_live_data(self):
        linked = self.assert_ok(self.link(self.f.organic))['publications']
        ownership.unlink_account(self.f.db, self.f.connection, self.f.a, self.f.fb)
        row = self.assert_ok(self.client.get(self.base))
        self.assertEqual(row['publications'], linked)
        self.assertEqual(set(linked[0]), {'library_item_id', 'created_at'})
        with self.assertRaises(ownership.OwnershipNotFound):
            ownership.get_item(self.f.db, self.f.connection, self.f.a, self.f.organic)
        self.assertEqual(self.link(self.f.organic).status_code, 404)  # Re-link still requires current access.
        self.assert_ok(self.client.delete(self.publication_url(self.f.organic)))

    def test_ad_reassignment_retains_original_company_association(self):
        linked = self.assert_ok(self.link(self.f.ad_a))['publications']
        ownership.reassign_ad(self.f.db, self.f.connection, self.f.a, self.f.b, self.f.ad_a)
        row = self.assert_ok(self.client.get(self.base))
        self.assertEqual(row['publications'], linked)
        self.assertEqual(set(linked[0]), {'library_item_id', 'created_at'})
        self.assertNotIn('a-secret', json.dumps(row))
        with self.assertRaises(ownership.OwnershipNotFound):
            ownership.performance(self.f.db, self.f.connection, self.f.a, self.f.ad_a)
        other = self.client.get(f'/api/meta/companies/{self.f.b}/ideas').json()
        self.assertEqual(other['items'], [])

    def test_meta_disconnect_preserves_membership_based_access(self):
        self.assert_ok(self.link(self.f.organic))
        self.assert_ok(self.feedback('liked'))
        library.disconnect(self.f.connection)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.status('used').status_code, 200)
        self.assertEqual(self.link(self.f.organic).status_code, 200)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM idea_publications').fetchone()['n'], 1)
        self.assertEqual(self.f.db.execute('SELECT feedback FROM ideas WHERE id=%s', (self.id,)).fetchone()['feedback'], 'liked')

    def test_archive_blocks_all_mutations_and_restore_resumes(self):
        self.assert_ok(self.link(self.f.organic))
        self.assert_ok(self.feedback('disliked', reason='Keep this reason'))
        before = self.client.get(self.base).json()
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a)
        for response in (self.status('published'), self.feedback('liked'), self.link(self.f.instagram),
                         self.client.delete(self.publication_url(self.f.organic))):
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM idea_publications').fetchone()['n'], 1)
        ownership.set_company_archived(self.f.db, self.f.connection, self.f.a, archived=False)
        self.assertEqual(self.client.get(self.base).json(), before)
        self.assert_ok(self.status('published'))
        self.assert_ok(self.feedback('liked'))
        self.assert_ok(self.link(self.f.instagram))
        self.assert_ok(self.client.delete(self.publication_url(self.f.organic)))

    def test_remove_publication_preserves_both_entities(self):
        self.assert_ok(self.link(self.f.organic))
        removed = self.assert_ok(self.client.delete(self.publication_url(self.f.organic)))
        self.assertEqual(removed['publications'], [])
        self.assertEqual(self.assert_ok(self.client.delete(self.publication_url(self.f.organic))), removed)
        self.assertIsNotNone(self.f.db.execute('SELECT id FROM ideas WHERE id=%s', (self.id,)).fetchone())
        self.assertIsNotNone(self.f.db.execute('SELECT id FROM meta_library_items WHERE id=%s', (self.f.organic,)).fetchone())

    def test_generation_evidence_and_request_replay_are_unchanged(self):
        self.assert_ok(self.status('published'))
        self.assert_ok(self.feedback('disliked', reason='New feedback'))
        updated = self.assert_ok(self.link(self.f.organic))
        self.assertEqual(self.client.get(self.base + '/evidence').json(), self.original_evidence)
        self.assertEqual(self.fixture.generate(body=self.body), updated)
        self.assertEqual(self.fixture.model.call_count, 1)

    def test_recent_feedback_context_is_bounded_scoped_and_frozen(self):
        self.assert_ok(self.feedback('disliked', reason='A specific reason'))
        self.assert_ok(self.status('discarded'))
        self.fixture.generate(company=self.f.b)
        second = self.fixture.generate(body={**self.body, 'request_id': str(uuid4()), 'history_limit': 1})
        context = self.fixture.model.call_args.args[0]['prior_ideas']
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]['id'], self.id)
        self.assertEqual(context[0]['status'], 'discarded')
        self.assertEqual(context[0]['feedback'], 'disliked')
        self.assertEqual(context[0]['feedback_reason'], 'A specific reason')
        self.assert_ok(self.feedback('none'))
        frozen = self.client.get(f"/api/meta/companies/{self.f.a}/ideas/{second['id']}/evidence").json()
        self.assertEqual(frozen['prior_ideas'], context)
        self.fixture.generate(body={**self.body, 'request_id': str(uuid4()), 'history_limit': 0})
        self.assertEqual(self.fixture.model.call_args.args[0]['prior_ideas'], [])
        history = self.client.get(f'/api/meta/companies/{self.f.a}/ideas?limit=100').json()['items']
        original = next(row for row in history if row['id'] == self.id)
        self.assertEqual(original['feedback'], 'none')
        self.assertEqual(original['status'], 'discarded')

    def test_database_constraints_and_generation_guards(self):
        statements = [
            ("UPDATE ideas SET status='scheduled' WHERE id=%s", (self.id,)),
            ("UPDATE ideas SET feedback='loved' WHERE id=%s", (self.id,)),
            ("UPDATE ideas SET feedback_reason='Not disliked' WHERE id=%s", (self.id,)),
            ("UPDATE ideas SET feedback='disliked',feedback_reason=repeat('x',2001) WHERE id=%s", (self.id,)),
            ("UPDATE ideas SET status='used',model='changed' WHERE id=%s", (self.id,)),
            ("UPDATE ideas SET feedback='liked',company_id=%s WHERE id=%s", (self.f.b, self.id)),
            ("UPDATE ideas SET evidence_sealed=false WHERE id=%s", (self.id,)),
            ("UPDATE idea_sources SET analysis_version=99 WHERE idea_id=%s", (self.id,)),
            ("INSERT INTO idea_publications VALUES (%s,%s,now())", (uuid4(), self.f.organic)),
            ("INSERT INTO idea_publications VALUES (%s,%s,now())", (self.id, uuid4())),
        ]
        for statement, args in statements:
            with self.subTest(statement=statement), self.assertRaises(psycopg.IntegrityError):
                self.f.db.execute(statement, args)
        self.assert_ok(self.link(self.f.organic))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.f.db.execute('INSERT INTO idea_publications VALUES (%s,%s,now())', (self.id, self.f.organic))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.f.db.execute('DELETE FROM meta_library_items WHERE id=%s', (self.f.organic,))

    def test_link_locks_against_ownership_and_archive_changes(self):
        original = ideas.add_publication
        def insert(db, *args):
            for mutation in (
                lambda other: ownership.unlink_account(other, self.f.connection, self.f.a, self.f.fb),
                lambda other: ownership.set_company_archived(other, self.f.connection, self.f.a),
            ):
                with self.assertRaises(psycopg.errors.LockNotAvailable), library.database() as other:
                    other.execute("SET LOCAL lock_timeout='50ms'")
                    mutation(other)
            return original(db, *args)
        with patch('app.idea_routes.ideas.add_publication', side_effect=insert):
            self.assert_ok(self.link(self.f.organic))

    def test_concurrent_duplicate_links_have_one_association(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.link(self.f.organic), range(2)))
        for result in results:
            self.assert_ok(result)
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(self.f.db.execute('SELECT count(*) AS n FROM idea_publications').fetchone()['n'], 1)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class IdeaFeedbackMigrationTests(unittest.TestCase):
    def test_001_through_009_upgrade_preserves_existing_008_evidence(self):
        schema = 'idea_009_upgrade_' + uuid4().hex
        with psycopg.connect(os.environ['TEST_DATABASE_URL'], autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            try:
                url = make_conninfo(os.environ['TEST_DATABASE_URL'], options=f'-csearch_path={schema}')
                with psycopg.connect(url, autocommit=True, row_factory=dict_row) as db:
                    paths = sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('00[1-9]_*.sql'))
                    self.assertEqual(len(paths), 9)
                    for path in paths[:8]:
                        db.execute(path.read_text())
                    connection = db.execute("INSERT INTO meta_connections(external_user_id,expires_at) VALUES ('upgrade',now()+interval '1 day') RETURNING id").fetchone()['id']
                    company = db.execute("INSERT INTO companies(connection_id,name) VALUES (%s,'Existing company') RETURNING id", (connection,)).fetchone()['id']
                    request, identity = uuid4(), uuid4()
                    with db.transaction():
                        db.execute("INSERT INTO idea_generation_requests(company_id,request_id,request_hash) VALUES (%s,%s,repeat('0',64))", (company, request))
                        db.execute("""INSERT INTO ideas(id,company_id,title,concept,script,recommendation_version,model,
                            evidence_schema_version,evidence_captured_at,request_id,request_hash,prior_idea_evidence)
                            VALUES (%s,%s,'Old title','Old concept','Old script',3,'old-model',2,now(),%s,repeat('0',64),'[]')""", (identity,company,request))
                        db.execute("INSERT INTO idea_sources VALUES (%s,%s,0,1,'{}','{}')", (identity,uuid4()))
                        db.execute('UPDATE ideas SET evidence_sealed=true WHERE id=%s', (identity,))
                    before = db.execute('SELECT * FROM ideas WHERE id=%s', (identity,)).fetchone()
                    sources = db.execute('SELECT * FROM idea_sources').fetchall()
                    db.execute(paths[8].read_text())
                    after = db.execute('SELECT * FROM ideas WHERE id=%s', (identity,)).fetchone()
                    self.assertEqual(after.pop('feedback'), 'none')
                    self.assertIsNone(after.pop('feedback_reason'))
                    self.assertEqual(after, before)
                    self.assertEqual(db.execute('SELECT * FROM idea_sources').fetchall(), sources)
                    db.execute("UPDATE ideas SET status='used',feedback='liked' WHERE id=%s", (identity,))
                    with self.assertRaises(psycopg.errors.CheckViolation):
                        db.execute("UPDATE ideas SET model='tampered' WHERE id=%s", (identity,))
            finally:
                admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
