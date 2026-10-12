"""Disposable PostgreSQL tests for historical observations and legacy snapshot compatibility."""

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app import performance_observation_repository as history
from app.video_repository import get_analysis
from intelligence.observation_adapter import latest_observations_for_cohort, to_stage61_record
from intelligence.performance_comparison import compare

DATES = (date(2026, 1, 1), date(2026, 1, 7))
DETAILS = {"date_start": "2026-01-01", "date_stop": "2026-01-07",
           "account_currency": "EUR", "action_report_time": "impression",
           "action_attribution_windows": ["7d_click", "1d_view"],
           "impressions": 1000, "reach": 500, "clicks": 20,
           "spend": "10.00", "ctr": "2.0", "cpc": "0.50",
           "actions": None, "conversions": None, "video_play_actions": None}


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL")
class ObservationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.schema = "observation_test_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True)
        self.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_schema)
        self.url = make_conninfo(os.environ["TEST_DATABASE_URL"], options=f"-csearch_path={self.schema}")
        self.db = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
        self.addCleanup(self.db.close)
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            if migration.name == "015_performance_observations.sql":
                self.legacy_video = self.db.execute("""INSERT INTO videos
                    (duration_seconds,container,file_size_bytes)
                    VALUES (1,'mp4',100) RETURNING id""").fetchone()["id"]
                self.db.execute("""INSERT INTO video_performance(video_id,source,view_count)
                    VALUES (%s,'tiktok',42)""", (self.legacy_video,))
            self.db.execute(migration.read_text())
        self.user = SimpleNamespace(user_id=uuid4())
        self.db.execute("INSERT INTO user_profiles(user_id) VALUES (%s)", (self.user.user_id,))
        self.connection = self.db.execute("""INSERT INTO meta_connections(external_user_id,expires_at)
            VALUES ('fixture-owner',now()+interval '1 day') RETURNING id""").fetchone()["id"]
        self.company = self.db.execute("""INSERT INTO companies(connection_id,name)
            VALUES (%s,'Fixture') RETURNING id""", (self.connection,)).fetchone()["id"]
        self.other_company = self.db.execute("""INSERT INTO companies(connection_id,name)
            VALUES (%s,'Other') RETURNING id""", (self.connection,)).fetchone()["id"]
        for company in (self.company, self.other_company):
            self.db.execute("INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,'owner')",
                            (company, self.user.user_id))
        self.account_uuid = self.db.execute("""INSERT INTO meta_accounts(connection_id,platform,external_id,label)
            VALUES (%s,'meta_ads','act_123','Fixture') RETURNING id""", (self.connection,)).fetchone()["id"]
        self.db.execute("""INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
            VALUES (%s,%s,%s,'meta_ads')""", (self.company, self.connection, self.account_uuid))
        self.video = self.db.execute("""INSERT INTO videos(duration_seconds,container,file_size_bytes,meta_connection_id)
            VALUES (1,'mp4',100,%s) RETURNING id""", (self.connection,)).fetchone()["id"]
        self.item = self.db.execute("""INSERT INTO meta_library_items
            (connection_id,account_id,platform,external_id,content_type,label,video_id)
            VALUES (%s,%s,'meta_ads','456','ad','Fixture',%s) RETURNING id""",
            (self.connection, self.account_uuid, self.video)).fetchone()["id"]
        self.db.execute("""INSERT INTO company_ad_assignments
            (ad_item_id,company_id,connection_id,account_id)
            VALUES (%s,%s,%s,%s)""", (self.item, self.company, self.connection, self.account_uuid))
        self.env = patch.dict(os.environ, {"DATABASE_URL": self.url})
        self.env.start()
        self.addCleanup(self.env.stop)

    def cleanup_schema(self):
        try:
            self.admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        finally:
            self.admin.close()

    def save(self, details=None):
        return history.save_meta_ad_observation(
            self.user, self.company, self.connection, self.item,
            {"ad_id": "456", "account_id": "123", "placement_scope": "meta_all_placements"},
            {"performance_source": "meta_ads", "performance_metrics": {
                "view_count": None, "like_count": None, "comment_count": None,
                "share_count": None, "meta_ads": details or deepcopy(DETAILS)}})

    def read(self, user=None, company=None):
        return history.observations_for_comparison(
            user or self.user, company or self.company, source="meta_ads",
            provider_account_id="act_123", placement_scope="meta_all_placements",
            report_start=DATES[0], report_end=DATES[1],
            action_report_time="impression", attribution_windows=["7d_click", "1d_view"],
            account_currency="EUR")

    def test_migration_015_structure_and_legacy_data(self):
        columns = {row["column_name"]: (row["data_type"], row["udt_name"])
                   for row in self.db.execute("""SELECT column_name,data_type,udt_name
                       FROM information_schema.columns WHERE table_schema=current_schema()
                         AND table_name='performance_observations'""")}
        expected = {"id": "uuid", "company_id": "uuid", "connection_id": "uuid",
                    "account_uuid": "uuid", "item_uuid": "uuid", "video_id": "uuid",
                    "source": "text", "provider_object_type": "text",
                    "provider_object_id": "text", "provider_account_id": "text",
                    "placement_scope": "text", "exposure_type": "text",
                    "report_start": "date", "report_end": "date", "fetched_at": "timestamptz",
                    "account_currency": "text", "action_report_time": "text",
                    "attribution_windows": "_text", "metric_payload": "jsonb",
                    "provenance": "jsonb", "context_key": "text"}
        self.assertEqual({name: columns[name][1] for name in expected}, expected)
        constraints = self.db.execute("""SELECT contype,count(*) AS n FROM pg_constraint
            WHERE conrelid='performance_observations'::regclass GROUP BY contype""").fetchall()
        self.assertEqual({r["contype"]: r["n"] for r in constraints}.get("f", 0), 8)
        foreign_keys = [row["definition"] for row in self.db.execute("""SELECT
            pg_get_constraintdef(oid) AS definition FROM pg_constraint
            WHERE conrelid='performance_observations'::regclass AND contype='f'""")]
        for target in ("companies", "meta_accounts", "meta_library_items", "videos"):
            self.assertTrue(any(f"REFERENCES {target}(" in definition for definition in foreign_keys), target)
        indexes = {row["indexname"] for row in self.db.execute("""SELECT indexname
            FROM pg_indexes WHERE schemaname=current_schema()
              AND tablename='performance_observations'""")}
        self.assertTrue({"performance_observations_pkey", "performance_observations_cohort",
                         "performance_observations_object"} <= indexes)
        self.assertTrue(self.db.execute("""SELECT relrowsecurity FROM pg_class
            WHERE oid='performance_observations'::regclass""").fetchone()["relrowsecurity"])
        self.assertEqual(self.db.execute("""SELECT count(*) AS n FROM pg_policies
            WHERE schemaname=current_schema() AND tablename='performance_observations'""").fetchone()["n"], 0)
        triggers = {row["tgname"] for row in self.db.execute("""SELECT tgname FROM pg_trigger
            WHERE tgrelid='performance_observations'::regclass AND NOT tgisinternal""")}
        self.assertEqual(triggers, {"performance_observations_immutable",
                                    "performance_observations_validate_link"})
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM performance_observations").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM videos WHERE id=%s",
                                         (self.video,)).fetchone()["n"], 1)
        legacy = self.db.execute("""SELECT source,view_count FROM video_performance
            WHERE video_id=%s""", (self.legacy_video,)).fetchone()
        self.assertEqual((legacy["source"], legacy["view_count"]), ("tiktok", 42))
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM meta_library_items WHERE id=%s",
                                         (self.item,)).fetchone()["n"], 1)

    def test_database_to_comparison_latest_versions(self):
        ids = ["456", *[f"synthetic-ad-{number}" for number in range(1, 6)]]
        for number, ad_id in enumerate(ids):
            if number:
                item = self.db.execute("""INSERT INTO meta_library_items
                    (connection_id,account_id,platform,external_id,content_type,label)
                    VALUES (%s,%s,'meta_ads',%s,'ad','Synthetic') RETURNING id""",
                    (self.connection, self.account_uuid, ad_id)).fetchone()["id"]
                self.db.execute("""INSERT INTO company_ad_assignments
                    (ad_item_id,company_id,connection_id,account_id) VALUES (%s,%s,%s,%s)""",
                    (item, self.company, self.connection, self.account_uuid))
            else:
                item = self.item
            details = deepcopy(DETAILS)
            details["spend"] = f"{10 + number}.00"
            history.save_meta_ad_observation(self.user, self.company, self.connection, item,
                {"ad_id": ad_id, "account_id": "123", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": details}})
        older = self.read()
        self.assertEqual(len(older), 6)
        newest = deepcopy(DETAILS)
        newest["spend"] = "99.00"
        self.save(newest)
        historical = self.read()
        self.assertEqual(len(historical), 7)
        self.assertEqual(len({row["context_key"] for row in historical}), 6)
        target_history = [row for row in historical if row["provider_object_id"] == "456"]
        self.assertEqual(len(target_history), 2)
        self.assertEqual({row["metric_payload"]["spend"] for row in target_history},
                         {"10.00", "99.00"})
        self.assertEqual(len({row["id"] for row in target_history}), 2)
        self.assertEqual({row["context_key"] for row in target_history},
                         {target_history[0]["context_key"]})
        # Each ad has its own context key because provider object identity is
        # part of provenance; exact comparison context is in the repository filter.
        latest = latest_observations_for_cohort(historical)
        records = [to_stage61_record(row) for row in latest]
        target = next(row for row in records if row["provider_id"] == "456")
        report = compare(target, records, ["spend"])
        metric = report["metric_comparisons"][0]
        self.assertEqual(metric["sample_size"], 5)
        self.assertTrue(metric["eligibility"])
        self.assertEqual(metric["target_value"], "99.00")
        self.assertFalse(report["target_exclusion_proof"]["spend"]["cohort_has_target_alias"])
        self.assertEqual(len(report["target_exclusion_proof"]["spend"]["excluded_aliases"]), 1)
        self.assertIn("insufficient_peer_cohort", compare(target, records[:4], ["spend"])
                      ["metric_comparisons"][0]["abstention_reasons"])
        missing = deepcopy(DETAILS)
        missing["spend"] = None
        peer_item = self.db.execute("SELECT id FROM meta_library_items WHERE external_id='synthetic-ad-1'").fetchone()["id"]
        history.save_meta_ad_observation(self.user, self.company, self.connection, peer_item,
            {"ad_id": "synthetic-ad-1", "account_id": "123", "placement_scope": "meta_all_placements"},
            {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": missing}})
        latest = latest_observations_for_cohort(self.read())
        report = compare(target, [to_stage61_record(row) for row in latest], ["spend"])
        self.assertEqual(report["metric_comparisons"][0]["sample_size"], 4)
        self.assertIn("insufficient_peer_cohort", report["metric_comparisons"][0]["abstention_reasons"])

    def test_immutable_versions_snapshot_rollback_and_adapter(self):
        first = self.save()
        changed = deepcopy(DETAILS)
        changed["spend"] = "12.00"
        second = self.save(changed)
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["fetched_at"], second["fetched_at"])
        rows = history.observations_for_comparison(
            self.user, self.company, source="meta_ads", provider_account_id="act_123",
            placement_scope="meta_all_placements", report_start=DATES[0], report_end=DATES[1],
            action_report_time="impression", attribution_windows=["7d_click", "1d_view"],
            account_currency="EUR")
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["metric_payload"]["spend"] for row in rows], ["12.00", "10.00"])
        self.assertEqual((rows[0]["provider_object_id"], rows[0]["provider_account_id"],
                          rows[0]["placement_scope"], rows[0]["account_currency"]),
                         ("456", "act_123", "meta_all_placements", "EUR"))
        self.assertEqual((rows[0]["report_start"], rows[0]["report_end"],
                          rows[0]["attribution_windows"]), (*DATES, ["7d_click", "1d_view"]))
        self.assertEqual(rows[0]["action_report_time"], "impression")
        self.assertEqual(rows[0]["context_key"], rows[1]["context_key"])
        self.assertEqual(get_analysis(self.video, connection_id=self.connection)["performance_metrics"]["meta_ads"]["spend"], "12.00")
        adapted = to_stage61_record(rows[0])
        peers = [{**adapted, "provider_id": str(i), "reference": str(i)} for i in range(5)]
        self.assertTrue(compare(adapted, peers, ["spend"])["metric_comparisons"][0]["eligibility"])
        with self.assertRaises(psycopg.Error), patch.object(history, "_context_key", return_value="invalid"):
            rolled = deepcopy(DETAILS)
            rolled["spend"] = "99.00"
            self.save(rolled)
        self.assertEqual(get_analysis(self.video, connection_id=self.connection)["performance_metrics"]["meta_ads"]["spend"], "12.00")
        self.assertEqual(self.db.execute("SELECT count(*) AS n FROM performance_observations").fetchone()["n"], 2)
        with self.assertRaises(psycopg.Error):
            self.db.execute("UPDATE performance_observations SET account_currency='USD' WHERE id=%s", (first["id"],))
        with self.assertRaises(psycopg.Error):
            self.db.execute("DELETE FROM performance_observations WHERE id=%s", (first["id"],))

    def test_company_and_provider_identity_rejected(self):
        other_item = self.db.execute("""INSERT INTO meta_library_items
            (connection_id,account_id,platform,external_id,content_type,label)
            VALUES (%s,%s,'meta_ads','synthetic-other-ad','ad','Synthetic') RETURNING id""",
            (self.connection, self.account_uuid)).fetchone()["id"]
        self.db.execute("""INSERT INTO company_accounts(company_id,connection_id,account_id,account_platform)
            VALUES (%s,%s,%s,'meta_ads')""", (self.other_company, self.connection, self.account_uuid))
        self.db.execute("""INSERT INTO company_ad_assignments
            (ad_item_id,company_id,connection_id,account_id) VALUES (%s,%s,%s,%s)""",
            (other_item, self.other_company, self.connection, self.account_uuid))
        history.save_meta_ad_observation(self.user, self.other_company, self.connection, other_item,
            {"ad_id": "synthetic-other-ad", "account_id": "123", "placement_scope": "meta_all_placements"},
            {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        self.assertEqual(len(self.read(company=self.other_company)), 1)
        self.assertEqual(self.read(), [])
        other_user = SimpleNamespace(user_id=uuid4())
        self.db.execute("INSERT INTO user_profiles(user_id) VALUES (%s)", (other_user.user_id,))
        self.db.execute("INSERT INTO company_memberships(company_id,user_id,role) VALUES (%s,%s,'owner')",
                        (self.other_company, other_user.user_id))
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.read(user=other_user, company=self.company)
        with self.assertRaises(history.ObservationOwnershipError):
            history.save_meta_ad_observation(self.user, self.other_company, self.connection, self.item,
                {"ad_id": "456", "account_id": "123", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        for ad_id, account_id in (("wrong-ad", "123"), ("456", "999")):
            with self.assertRaises(history.ObservationOwnershipError):
                history.save_meta_ad_observation(self.user, self.company, self.connection, self.item,
                    {"ad_id": ad_id, "account_id": account_id,
                     "placement_scope": "meta_all_placements"},
                    {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        wrong_connection = self.db.execute("""INSERT INTO meta_connections(external_user_id,expires_at)
            VALUES ('synthetic-other-owner',now()+interval '1 day') RETURNING id""").fetchone()["id"]
        with self.assertRaises((history.ObservationOwnershipError, HTTPException)):
            history.save_meta_ad_observation(self.user, self.company, wrong_connection, self.item,
                {"ad_id": "456", "account_id": "123", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        unassigned = self.db.execute("""INSERT INTO meta_library_items
            (connection_id,account_id,platform,external_id,content_type,label)
            VALUES (%s,%s,'meta_ads','synthetic-unassigned','ad','Synthetic') RETURNING id""",
            (self.connection, self.account_uuid)).fetchone()["id"]
        with self.assertRaises(history.ObservationOwnershipError):
            history.save_meta_ad_observation(self.user, self.company, self.connection, unassigned,
                {"ad_id": "synthetic-unassigned", "account_id": "123",
                 "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        original = self.save()
        wrong_video = self.db.execute("""INSERT INTO videos
            (duration_seconds,container,file_size_bytes,meta_connection_id)
            VALUES (1,'mp4',100,%s) RETURNING id""", (self.connection,)).fetchone()["id"]
        with self.assertRaises(psycopg.Error):
            self.db.execute("""INSERT INTO performance_observations
                (company_id,connection_id,account_uuid,item_uuid,video_id,source,
                 provider_object_type,provider_object_id,provider_account_id,placement_scope,
                 exposure_type,report_start,report_end,account_currency,action_report_time,
                 attribution_windows,metric_payload,provenance,context_key)
                SELECT company_id,connection_id,account_uuid,item_uuid,%s,source,
                 provider_object_type,provider_object_id,provider_account_id,placement_scope,
                 exposure_type,report_start,report_end,account_currency,action_report_time,
                 attribution_windows,metric_payload,provenance,context_key
                FROM performance_observations WHERE id=%s""", (wrong_video, original["id"]))
