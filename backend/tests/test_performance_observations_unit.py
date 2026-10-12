"""Synthetic observation conversion and context identity tests."""

from datetime import date, datetime, timezone
import unittest
from uuid import uuid4

from app.performance_observation_repository import _context_key
from intelligence.observation_adapter import to_stage61_record
from intelligence.performance_comparison import compare


class ObservationUnitTests(unittest.TestCase):
    def observation(self):
        return {"id": uuid4(), "company_id": uuid4(), "source": "meta_ads",
                "provider_object_id": "synthetic-ad", "provider_account_id": "synthetic-account",
                "placement_scope": "meta_all_placements", "exposure_type": "paid",
                "report_start": date(2026, 1, 1), "report_end": date(2026, 1, 7),
                "fetched_at": datetime(2026, 1, 8, tzinfo=timezone.utc),
                "account_currency": "EUR", "action_report_time": "impression",
                "attribution_windows": ["7d_click", "1d_view"],
                "metric_payload": {"date_start": "2026-01-01", "date_stop": "2026-01-07",
                    "account_currency": "EUR", "action_report_time": "impression",
                    "action_attribution_windows": ["7d_click", "1d_view"],
                    "impressions": 1000, "reach": 500, "clicks": 20,
                    "spend": "10.00", "ctr": "2", "cpc": "0.50"}}

    def test_adapter_preserves_exact_context_and_compares(self):
        observation = self.observation()
        record = to_stage61_record(observation)
        self.assertEqual(record["provider_id"], observation["provider_object_id"])
        self.assertEqual(record["account_id"], observation["provider_account_id"])
        self.assertEqual(record["workspace_id"], str(observation["company_id"]))
        self.assertEqual(record["performance_metrics"]["meta_ads"]["account_currency"], "EUR")
        peers = [{**record, "reference": str(i), "provider_id": str(i)} for i in range(5)]
        result = compare(record, peers, ["spend"])["metric_comparisons"][0]
        self.assertTrue(result["eligibility"])

    def test_adapter_rejects_context_mismatch(self):
        for change in ({"placement_scope": "instagram"}, {"account_currency": "USD"},
                       {"attribution_windows": ["1d_view"]}, {"report_end": date(2026, 1, 8)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                to_stage61_record({**self.observation(), **change})

    def test_context_key_is_stable_and_separates_attribution(self):
        observation = self.observation()
        details = observation["metric_payload"]
        key = _context_key(observation["company_id"], "ad", "account", details)
        self.assertEqual(key, _context_key(observation["company_id"], "ad", "account", dict(details)))
        self.assertNotEqual(key, _context_key(observation["company_id"], "ad", "account",
                                               {**details, "action_attribution_windows": ["1d_view"]}))
