"""Synthetic Meta responses only. No owned account values or credentials."""

import unittest
from datetime import date
from unittest.mock import patch

from app import meta
from intelligence.real_meta_history import collect, experiment

ACCOUNT = "act_123"
SINCE, UNTIL = date(2026, 1, 1), date(2026, 1, 7)


class Client:
    def __init__(self, count=6, changes=None):
        self.count = count
        self.changes = changes or {}
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path == "me/adaccounts":
            return {"data": [{"id": ACCOUNT, "name": "private account"}]}
        if path == f"{ACCOUNT}/ads":
            first = params.get("after") is None
            ids = range(1, min(self.count, 3) + 1) if first else range(4, self.count + 1)
            return {"data": [{"id": str(i), "name": "private ad"} for i in ids],
                    "paging": {"next": "provider-url", "cursors": {"after": "next"}} if first and self.count > 3 else {}}
        if path.endswith("/insights"):
            ad_id = path.split("/")[0]
            row = {"ad_id": ad_id, "account_id": "123", "account_currency": "EUR",
                   "date_start": SINCE.isoformat(), "date_stop": UNTIL.isoformat(),
                   "impressions": "1000", "reach": "500", "clicks": "20",
                   "spend": "10.00", "ctr": "2.1", "cpc": "0.50",
                   "actions": [{"action_type": "link_click", "7d_click": "7", "1d_view": "1"}]}
            row.update(self.changes.get(ad_id, {}))
            return {"data": [row]}
        if path.isdigit():
            return {"id": path, "account_id": self.changes.get(path, {}).get("identity_account", "123")}
        raise AssertionError("unexpected path")


class RealMetaHistoryTests(unittest.TestCase):
    def test_discovery_pagination_identity_and_shared_window(self):
        client = Client()
        records, audit = collect(client, "workspace", ACCOUNT, SINCE, UNTIL)
        self.assertEqual((audit["discovered"], audit["eligible"], audit["excluded"]), (6, 6, 0))
        self.assertEqual([row["provider_id"] for row in records], list("123456"))
        self.assertTrue(all(row["account_id"] == ACCOUNT and row["platform"] == "meta_all_placements" for row in records))
        requests = [params for path, params in client.calls if path.endswith("/insights")]
        self.assertEqual(len(requests), 6)
        self.assertTrue(all('"since": "2026-01-01"' in query["time_range"] and
                            '"until": "2026-01-07"' in query["time_range"] and
                            "breakdowns" not in query for query in requests))
        self.assertEqual(experiment(records)["ctr_vs_derived_click_rate"], {"pairs": 6, "different": 6})

    def test_account_mismatch_and_malformed_response_abstain(self):
        client = Client(changes={"1": {"identity_account": "999"},
                                 "2": {"date_stop": "2026-01-06"},
                                 "3": {"account_currency": None}})
        records, audit = collect(client, "workspace", ACCOUNT, SINCE, UNTIL)
        self.assertEqual(audit["eligible"], 3)
        self.assertEqual(audit["exclusion_reasons"], {"account_mismatch": 1,
                         "malformed_or_unavailable_insights": 1, "missing_currency": 1})
        self.assertEqual(experiment(records)["status"], "insufficient_real_cohort")

    def test_owned_account_required_and_no_persistence(self):
        client = Client()
        with self.assertRaises(meta.MetaPermissionError):
            collect(client, "workspace", "act_999", SINCE, UNTIL)
        with patch("builtins.open", side_effect=AssertionError("unexpected write")):
            records, _ = collect(Client(), "workspace", ACCOUNT, SINCE, UNTIL)
            aggregate = experiment(records)
        self.assertNotIn("private", str(aggregate))
        self.assertNotIn("provider_id", str(aggregate))
        self.assertIn("action:actions:link_click:7d_click", aggregate["metrics_comparable"])


if __name__ == "__main__":
    unittest.main()
