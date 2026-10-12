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
from intelligence.observation_adapter import to_stage61_record
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

    def test_immutable_versions_snapshot_rollback_and_adapter(self):
        first = self.save()
        changed = deepcopy(DETAILS)
        changed["spend"] = "12.00"
        second = self.save(changed)
        self.assertNotEqual(first["id"], second["id"])
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
        self.assertEqual(history.observations_for_comparison(
            self.user, self.other_company, source="meta_ads", provider_account_id="act_123",
            placement_scope="meta_all_placements", report_start=DATES[0], report_end=DATES[1],
            action_report_time="impression", attribution_windows=["7d_click", "1d_view"],
            account_currency="EUR"), [])
        with self.assertRaises(history.ObservationOwnershipError):
            history.save_meta_ad_observation(self.user, self.other_company, self.connection, self.item,
                {"ad_id": "456", "account_id": "123", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
        with self.assertRaises(history.ObservationOwnershipError):
            history.save_meta_ad_observation(self.user, self.company, self.connection, self.item,
                {"ad_id": "456", "account_id": "999", "placement_scope": "meta_all_placements"},
                {"performance_source": "meta_ads", "performance_metrics": {"meta_ads": deepcopy(DETAILS)}})
