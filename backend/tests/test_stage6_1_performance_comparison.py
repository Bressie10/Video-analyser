"""Deterministic synthetic Stage 6.1 corpus; no owned account or semantic data."""

import copy
import json
import unittest
from decimal import Decimal

from intelligence.performance_comparison import compare, metric_definition


def organic(name, value, **changes):
    row = {"reference": name, "provider_id": name, "public_url": None,
           "workspace_id": "workspace-a", "platform": "instagram",
           "performance_source": "instagram", "exposure_type": "organic",
           "account_id": "account-a", "content_type": "reel", "declared_format": "vertical",
           "published_at": "2026-10-01T00:00:00+00:00", "observed_at": "2026-10-08T00:00:00+00:00",
           "fetched_at": "2026-10-08T00:00:00+00:00",
           "performance_metrics": {"view_count": value}}
    row.update(changes)
    return row


def paid(name, impressions=1000, clicks=20, spend="10", **changes):
    row = {"reference": name, "provider_id": name, "public_url": None,
           "workspace_id": "workspace-a", "platform": "meta_all_placements",
           "performance_source": "meta_ads", "exposure_type": "paid",
           "account_id": "ad-account-a", "fetched_at": "2026-10-08T00:00:00+00:00",
           "performance_metrics": {"meta_ads": {
               "date_start": "2026-10-01", "date_stop": "2026-10-07",
               "account_currency": "EUR", "action_report_time": "impression",
               "action_attribution_windows": ["7d_click", "1d_view"],
               "impressions": impressions, "reach": 500, "clicks": clicks,
               "spend": spend, "ctr": "2", "cpc": "0.5",
               "actions": [{"action_type": "purchase", "7d_click": "2", "1d_view": "1"}],
               "conversions": [{"action_type": "purchase", "7d_click": "2", "1d_view": "1"}],
               "video_play_actions": [{"action_type": "video_view", "7d_click": "10", "1d_view": "4"}]}}}
    row.update(changes)
    return row


def changed_ad(row, **changes):
    result = copy.deepcopy(row)
    result["performance_metrics"]["meta_ads"].update(changes)
    return result


def result(report, metric):
    return next(item for item in report["metric_comparisons"] if item["metric_id"] == metric)


class Stage61ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.organic_target = organic("target", 40)
        self.organic_peers = [organic(f"peer-{i}", value) for i, value in enumerate((5, 10, 10, 15, 20))]
        self.paid_target = paid("ad-target")
        self.paid_peers = [paid(f"ad-{i}", impressions=value) for i, value in
                           enumerate((500, 750, 1000, 1250, 1500))]

    def test_paid_scope_requires_explicit_combined_delivery(self):
        for scope in ("facebook", "instagram", None):
            with self.subTest(scope=scope):
                report = compare(paid("target", platform=scope), self.paid_peers, ["impressions"])
                self.assertFalse(result(report, "impressions")["eligibility"])
        mixed = compare(self.paid_target, [*self.paid_peers[:4], paid("mixed", platform="facebook")], ["impressions"])
        self.assertIn("platform_mismatch", mixed["excluded_candidate_peers"]["impressions"][0]["reasons"])
        self.assertIn("insufficient_peer_cohort", result(mixed, "impressions")["abstention_reasons"])

    def test_organic_exact_math_and_order_independence(self):
        report = compare(self.organic_target, self.organic_peers, ["view_count"])
        row = result(report, "view_count")
        self.assertTrue(row["eligibility"])
        self.assertEqual((row["median"], row["delta"], row["ratio"], row["mad"]),
                         ("10", "30", "4", "5"))
        self.assertEqual((row["percentile"], row["age_matched_percentile"]), (100, 100))
        self.assertAlmostEqual(float(row["robust_deviation"]), 30 / (1.4826 * 5))
        self.assertEqual(report, compare(self.organic_target, list(reversed(self.organic_peers)), ["view_count"]))

    def test_paid_raw_and_derived_metrics(self):
        metrics = ["impressions", "ctr", "cpc", "cpm", "frequency", "derived_click_rate",
                   "action:actions:purchase:7d_click", "action:video_play_actions:video_view:1d_view",
                   "action:conversions:purchase:7d_click",
                   "cost_per_action:conversions:purchase:7d_click"]
        report = compare(self.paid_target, self.paid_peers, metrics)
        self.assertTrue(all(row["eligibility"] for row in report["metric_comparisons"]))
        self.assertEqual(Decimal(result(report, "cpm")["target_value"]), 10)
        self.assertEqual(result(report, "frequency")["target_value"], "2")
        self.assertEqual(result(report, "derived_click_rate")["target_value"], "2.00")
        self.assertEqual(result(report, "cost_per_action:conversions:purchase:7d_click")["target_value"], "5")
        self.assertEqual(result(report, "action:conversions:purchase:7d_click")["target_value"], "2")
        self.assertEqual(result(report, "action:video_play_actions:video_view:1d_view")["target_value"], "4")
        self.assertNotEqual(result(report, "ctr")["context_fingerprint"],
                            result(report, "derived_click_rate")["context_fingerprint"])
        self.assertEqual(result(report, "impressions")["median"], "1000")
        self.assertEqual(result(report, "impressions")["method_abstentions"], [])

    def test_target_alias_and_dedup_are_audited(self):
        target_alias = organic("alias", 999, provider_id=None, public_url="https://example.test/target")
        target_bridge = organic("bridge", 999, provider_id="target", public_url="https://example.test/target")
        duplicate = organic("duplicate", 999, provider_id=self.organic_peers[0]["provider_id"])
        report = compare(self.organic_target, [*self.organic_peers, target_bridge, target_alias, duplicate], ["view_count"])
        row = result(report, "view_count")
        self.assertEqual(row["sample_size"], 5)
        self.assertEqual(len(report["target_exclusion_proof"]["view_count"]["excluded_aliases"]), 2)
        self.assertFalse(report["target_exclusion_proof"]["view_count"]["cohort_has_target_alias"])
        self.assertEqual(len(report["deduplicated_records"]["view_count"]), 1)
        reasons = {item["identity"]["reference"]: item["reasons"]
                   for item in report["excluded_candidate_peers"]["view_count"]}
        self.assertEqual(reasons["alias"], ["target_identity_alias"])
        self.assertEqual(reasons["bridge"], ["target_identity_alias"])

    def test_organic_rejections(self):
        cases = [
            (organic("workspace", 1, workspace_id="other"), "workspace_mismatch"),
            (organic("platform", 1, platform="facebook", performance_source="facebook"), "performance_source_mismatch"),
            (organic("account", 1, account_id="other"), "account_mismatch"),
            (paid("paid"), "performance_source_mismatch"),
            (organic("format", 1, declared_format="square"), "declared_format_mismatch"),
            (organic("age", 1, published_at="2026-09-01T00:00:00+00:00"), "publication_age_mismatch"),
            (organic("missing-time", 1, published_at=None), "missing_publication_or_observation_time"),
            (organic("other-definition", 1, metric_definitions={"view_count": "different"}), "provider_metric_definition_mismatch"),
            (organic("missing", {}, performance_metrics={}), "missing_metric"),
            (organic("null", None), "missing_metric"),
        ]
        report = compare(self.organic_target, [*self.organic_peers, *(row for row, _ in cases)], ["view_count"])
        reasons = {item["identity"]["reference"]: item["reasons"] for item in report["excluded_candidate_peers"]["view_count"]}
        for row, reason in cases:
            self.assertIn(reason, reasons[row["reference"]])
        self.assertIn("insufficient_peer_cohort", result(compare(self.organic_target, self.organic_peers[:4], ["view_count"]), "view_count")["abstention_reasons"])
        self.assertIn("missing_publication_or_observation_time", result(compare(organic("no-time", 3, published_at=None), self.organic_peers, ["view_count"]), "view_count")["abstention_reasons"])

    def test_paid_context_and_metric_rejections(self):
        cases = [
            (paid("other-account", account_id="other"), "account_mismatch"),
            (paid("other-platform", platform="facebook"), "platform_mismatch"),
            (changed_ad(paid("usd"), account_currency="USD"), "account_currency_mismatch"),
            (changed_ad(paid("period"), date_stop="2026-10-08"), "date_stop_mismatch"),
            (changed_ad(paid("report-time"), action_report_time="conversion"), "action_report_time_mismatch"),
            (changed_ad(paid("windows"), action_attribution_windows=["1d_view"]), "action_attribution_windows_mismatch"),
            (changed_ad(paid("action-type"), conversions=[{"action_type": "lead", "7d_click": "2"}]), "missing_action_type"),
            (changed_ad(paid("action-window"), conversions=[{"action_type": "purchase", "7d_click": None}]), "missing_attribution_window_value"),
        ]
        metric = "cost_per_action:conversions:purchase:7d_click"
        report = compare(self.paid_target, [*self.paid_peers, *(row for row, _ in cases)], [metric])
        reasons = {item["identity"]["reference"]: item["reasons"] for item in report["excluded_candidate_peers"][metric]}
        for row, reason in cases:
            self.assertIn(reason, reasons[row["reference"]])
        self.assertNotEqual(result(compare(self.paid_target, self.paid_peers, [metric]), metric)["context_fingerprint"],
                            result(compare(self.paid_target, self.paid_peers, ["cost_per_action:conversions:purchase:1d_view"]),
                                   "cost_per_action:conversions:purchase:1d_view")["context_fingerprint"])

    def test_missing_zero_and_math_abstentions(self):
        for metric, changed, reason in (
            ("cpm", {"impressions": 0}, "zero_denominator"),
            ("frequency", {"reach": 0}, "zero_denominator"),
            ("derived_click_rate", {"clicks": None}, "missing_metric"),
            ("cost_per_action:conversions:purchase:7d_click",
             {"conversions": [{"action_type": "purchase", "7d_click": "0"}]}, "zero_denominator"),
        ):
            target = changed_ad(self.paid_target, **changed)
            self.assertIn(reason, result(compare(target, self.paid_peers, [metric]), metric)["abstention_reasons"])
        zeros = [organic(f"zero-{i}", 0) for i in range(5)]
        row = result(compare(self.organic_target, zeros, ["view_count"]), "view_count")
        self.assertTrue(row["eligibility"])
        self.assertEqual(set(row["method_abstentions"]),
                         {"ratio_zero_median", "log_ratio_zero_median", "robust_deviation_zero_mad"})
        self.assertIn("missing_metric", result(compare(organic("target-null", None), self.organic_peers,
                                                       ["view_count"]), "view_count")["abstention_reasons"])
        self.assertIn("missing_currency", result(compare(changed_ad(self.paid_target, account_currency=None),
                                                         self.paid_peers, ["cpm"]), "cpm")["abstention_reasons"])
        self.assertIn("missing_action_type", result(compare(changed_ad(self.paid_target, conversions=[]),
                                                            self.paid_peers,
                                                            ["action:conversions:purchase:7d_click"]),
                                                     "action:conversions:purchase:7d_click")["abstention_reasons"])
        colon_action = changed_ad(self.paid_target, conversions=[{"action_type": "offsite_conversion:purchase",
                                                                "7d_click": "2", "1d_view": "1"}])
        self.assertTrue(result(compare(colon_action, [changed_ad(peer, conversions=colon_action["performance_metrics"]["meta_ads"]["conversions"])
                                                       for peer in self.paid_peers],
                                       ["action:conversions:offsite_conversion:purchase:7d_click"]),
                               "action:conversions:offsite_conversion:purchase:7d_click")["eligibility"])

    def test_registry_and_structured_output_have_no_causal_claim(self):
        for metric in ("view_count", "impressions", "ctr", "cpc", "cpm", "frequency",
                       "derived_click_rate", "cost_per_action:conversions:purchase:7d_click"):
            definition = metric_definition(metric, "instagram" if metric == "view_count" else "meta_ads")
            self.assertEqual(set(definition), {"metric_id", "description", "unit", "source", "exposure_type",
                                               "raw_or_derived", "formula", "required_inputs", "comparison_direction",
                                               "limitations"})
        emitted = json.dumps(compare(self.organic_target, self.organic_peers, ["view_count"])).lower()
        for phrase in ("caused", "drove", "because of", "resulted in", "this technique improved"):
            self.assertNotIn(phrase, emitted)
        self.assertNotIn("performance_score", emitted)


if __name__ == "__main__":
    unittest.main()
