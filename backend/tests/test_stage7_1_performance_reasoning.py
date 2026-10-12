"""Small synthetic Stage 7.1 evaluation set using real Stage 6 reports."""

from copy import deepcopy
import json
import unittest

from intelligence.performance_comparison import compare
from intelligence.performance_reasoning import evidence_summary, guard_language, reason


def paid(name, **changes):
    details = {"date_start": "2026-01-01", "date_stop": "2026-01-07",
               "account_currency": "EUR", "action_report_time": "impression",
               "action_attribution_windows": ["7d_click", "1d_view"],
               "impressions": 1000, "reach": 500, "clicks": 20,
               "spend": "10", "ctr": "2", "cpc": "1",
               "actions": [{"action_type": "purchase", "7d_click": "2"}],
               "conversions": [{"action_type": "purchase", "7d_click": "2"}]}
    details.update(changes)
    return {"reference": name, "provider_id": name, "public_url": None,
            "workspace_id": "synthetic-workspace", "platform": "meta_all_placements",
            "performance_source": "meta_ads", "exposure_type": "paid",
            "account_id": "synthetic-account", "fetched_at": "2026-01-08T00:00:00+00:00",
            "performance_metrics": {"meta_ads": details}}


def comparison(metrics, *, target=None, peers=5):
    target = paid("synthetic-target", **(target or {}))
    cohort = [paid(f"synthetic-peer-{i}") for i in range(peers)]
    return compare(target, cohort, metrics)


def organic(name, views):
    return {"reference": name, "provider_id": name, "public_url": None,
            "workspace_id": "synthetic-workspace", "platform": "instagram",
            "performance_source": "instagram", "exposure_type": "organic",
            "account_id": "synthetic-account", "content_type": "reel", "declared_format": "vertical",
            "published_at": "2026-01-01T00:00:00+00:00",
            "observed_at": "2026-01-08T00:00:00+00:00",
            "fetched_at": "2026-01-08T00:00:00+00:00",
            "performance_metrics": {"view_count": views}}


class PerformanceReasoningTests(unittest.TestCase):
    def test_compact_synthetic_evaluation_set(self):
        # Expected evidence, not prose snapshots. Every case uses Stage 6 compare.
        cases = [
            ("strong_click", ["ctr"], {"ctr": "4"}, 5, {"ctr"}, set()),
            ("weak_click", ["ctr"], {"ctr": "0.5"}, 5, {"ctr"}, set()),
            ("high_ctr_high_cpc", ["ctr", "cpc"], {"ctr": "4", "cpc": "2"}, 5,
             {"ctr", "cpc"}, {("ctr", "cpc")}),
            ("low_cpm_average_ctr", ["cpm", "ctr"], {"spend": "5"}, 5, {"cpm"}, set()),
            ("high_spend_average_efficiency", ["spend", "ctr", "cpc"], {"spend": "20"}, 5,
             {"spend"}, set()),
            ("actions_expensive", ["action:actions:purchase:7d_click",
               "cost_per_action:actions:purchase:7d_click"],
             {"actions": [{"action_type": "purchase", "7d_click": "4"}], "spend": "40"}, 5,
             {"action:actions:purchase:7d_click", "cost_per_action:actions:purchase:7d_click"},
             {("action:actions:purchase:7d_click", "cost_per_action:actions:purchase:7d_click")}),
            ("near_baseline", ["ctr", "cpc"], {}, 5, set(), set()),
            ("one_eligible", ["ctr", "cpc"], {"ctr": "4", "cpc": None}, 5, {"ctr"}, set()),
            ("several_abstentions", ["ctr", "cpc", "spend"],
             {"ctr": None, "cpc": None, "spend": None}, 5, set(), set()),
            ("minimum_five", ["impressions"], {"impressions": 2000}, 5, {"impressions"}, set()),
            ("larger_cohort", ["ctr"], {"ctr": "4"}, 9, {"ctr"}, set()),
            ("zero_mad", ["ctr"], {"ctr": "4"}, 5, {"ctr"}, set()),
            ("high_impressions_low_ctr", ["impressions", "ctr"],
             {"impressions": 2000, "ctr": "0.5"}, 5,
             {"impressions", "ctr"}, {("impressions", "ctr")}),
            ("raw_derived_conflict", ["ctr", "derived_click_rate"],
             {"ctr": "4", "clicks": 10}, 5,
             {"ctr", "derived_click_rate"}, {("ctr", "derived_click_rate")}),
        ]
        for name, metrics, target, peers, expected, expected_conflicts in cases:
            with self.subTest(name=name):
                report = comparison(metrics, target=target, peers=peers)
                output = reason(report)
                self.assertEqual({row["metric_id"] for row in output["notable_metrics"]}, expected)
                self.assertEqual({tuple(row["metric_ids"]) for row in output["mixed_signals"]}, expected_conflicts)
                self.assertTrue(all(row["sample_size"] == peers for row in output["notable_metrics"]))
                self.assertNotIn("overall_score", output)
                self.assertNotIn("significant", json.dumps(output).lower())
                self.assertNotIn("all your ads", output["summary"].lower())
                if name == "zero_mad":
                    fact = evidence_summary(report)["metrics"][0]
                    self.assertIsNone(fact["robust_deviation"])
                    self.assertIn("robust_deviation_zero_mad", fact["method_abstentions"])
                if name == "larger_cohort":
                    self.assertFalse(any("limited resolution" in item for item in output["limitations"]))
                if name == "several_abstentions":
                    self.assertEqual(len(output["abstentions"]), 3)

    def test_zero_median_and_method_abstention(self):
        target = paid("synthetic-target", spend="10")
        peers = [paid(f"synthetic-peer-{i}", spend="0") for i in range(5)]
        output = reason(compare(target, peers, ["spend"]))
        row = output["notable_metrics"][0]
        self.assertIsNone(row["ratio_to_median"])
        self.assertEqual(row["percentile"], 100)
        evidence = evidence_summary(compare(target, peers, ["spend"]))
        self.assertIn("ratio_zero_median", evidence["metrics"][0]["method_abstentions"])

    def test_organic_counts_remain_observational(self):
        report = compare(organic("synthetic-target", 40),
                         [organic(f"synthetic-peer-{i}", 10) for i in range(5)], ["view_count"])
        output = reason(report)
        self.assertIn("peer posts", output["summary"])
        self.assertEqual(output["notable_metrics"][0]["direction_semantics"],
                         "higher_means_more_observed_count")
        self.assertNotIn("better", output["summary"].lower())

    def test_summary_whitelists_performance_only_and_keeps_exact_values(self):
        report = comparison(["ctr", "cpc"], target={"ctr": "4", "cpc": None})
        report.update({"transcript": "SECRET_TRANSCRIPT", "motion_events": "SECRET_MOTION",
                       "semantic_labels": "SECRET_SEMANTIC", "recommendations": "SECRET_RECOMMENDATION",
                       "company_profile": "SECRET_PROFILE", "previous_reasoning": "SECRET_REASONING"})
        evidence = evidence_summary(report)
        serialized = json.dumps(evidence)
        self.assertNotIn("SECRET_", serialized)
        self.assertEqual(evidence["metrics"][0]["target_value"], "4")
        self.assertEqual(evidence["unavailable_metrics"][0]["metric_id"], "cpc")
        self.assertIn("missing_metric", evidence["unavailable_metrics"][0]["abstention_reasons"])

    def test_small_cohort_and_direction_semantics(self):
        output = reason(comparison(["spend", "frequency"],
                                   target={"spend": "20", "reach": 250}))
        self.assertIn("Among 5 comparable peer ads", output["summary"])
        self.assertTrue(any("limited resolution" in item for item in output["limitations"]))
        self.assertEqual({row["direction_semantics"] for row in output["notable_metrics"]},
                         {"higher_means_more_spend", "higher_means_more_impressions_per_reached_account"})
        self.assertNotIn("better", json.dumps(output).lower())
        self.assertIn("reported spend was above the cohort median", output["summary"])

    def test_rejects_unvalidated_or_malformed_stage6_data(self):
        report = comparison(["ctr"])
        for change in ({"schema_version": "unexpected"}, {"comparison_family": "mixed"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                evidence_summary({**report, **change})
        for field, value in (("percentile", 101), ("sample_size", 4),
                             ("ratio", "NaN"), ("context_fingerprint", "bad")):
            with self.subTest(field=field):
                malformed = deepcopy(report)
                malformed["metric_comparisons"][0][field] = value
                with self.assertRaises(ValueError):
                    evidence_summary(malformed)
        malformed = deepcopy(report)
        malformed["metric_comparisons"][0]["metric_definition"]["description"] = "A hook caused results"
        with self.assertRaises(ValueError):
            evidence_summary(malformed)

    def test_causal_language_guard(self):
        for statement in ("The hook caused higher CTR.", "This causes a better result.",
                          "The ad worked because of the opening.", "The ad worked because it had a hook.",
                          "Spend drove conversions.", "This technique improved CPC.",
                          "This proves success."):
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                guard_language(statement)
        self.assertEqual(guard_language("Observed CTR was higher among peers."),
                         "Observed CTR was higher among peers.")
