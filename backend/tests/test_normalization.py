"""Synthetic, offline comparisons; no provider data or network access."""

import copy
import unittest
from datetime import datetime, timedelta, timezone

from intelligence.normalization import evaluate, evaluate_baseline
from intelligence.run_normalization import run
from intelligence.schemas.benchmark import BenchmarkVideo
from intelligence.versions import BENCHMARK_VERSION

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def video(reference, value, *, account="creator-a", platform="instagram", exposure="organic",
          metric="views", age=7, source=None):
    published = NOW - timedelta(days=age)
    raw = {
        "schema_version": BENCHMARK_VERSION,
        "source": {"platform": platform, "provider_identifier": source or reference,
                   "public_url": None, "reference": reference,
                   "acquisition_method": "synthetic", "fetched_at": NOW},
        "creator": {"account_identifier": account, "account_url": None,
                    "follower_count": None, "follower_count_observed_at": None},
        "publication": {"published_at": published, "content_type": "reel",
                        "declared_format": None},
        "performance": {"fetched_at": NOW, "source": "synthetic provider snapshot",
                        "exposure": exposure, "metrics": {metric: value},
                        "metric_definitions": {metric: {"description": "Synthetic metric",
                                                         "unit": "count", "measurement_basis": "test"}},
                        "observation_window_start": published,
                        "observation_window_end": NOW, "attribution_context": None},
        "analysis": None, "baseline": None, "provenance_notes": ["synthetic fixture"],
    }
    return BenchmarkVideo.model_validate(raw)


def with_baseline(target, *, method="median", sample_size=20):
    raw = target.model_dump()
    raw["baseline"] = {
        "source": "creator-a export", "metrics": {"views": 10},
        "metric_definitions": raw["performance"]["metric_definitions"],
        "sample_size": sample_size, "window_start": NOW - timedelta(days=90),
        "window_end": NOW, "cohort_definition": "All creator-a organic Reels in window",
        "method_reference": method,
    }
    return BenchmarkVideo.model_validate(raw)


def baseline_context(**changes):
    context = {"platform": "instagram", "account_identifier": "creator-a", "exposure": "organic",
               "snapshot_source": "synthetic provider snapshot", "content_type": "reel",
               "declared_format": None, "attribution_context": None,
               "observation_window_basis": "publication_to_fetch",
               "publication_age_min_days": 5, "publication_age_max_days": 9,
               "target_excluded": True}
    return {**context, **changes}


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.target = video("target", 40)
        self.cohort = [video(f"peer-{i}", value) for i, value in enumerate((5, 10, 10, 15, 20))]

    def results(self, peers=None, target=None):
        return {row["method"]: row for row in evaluate(peers if peers is not None else self.cohort,
                                                         target or self.target, "views")}

    def test_median_ratio_log_percentile_and_age(self):
        rows = self.results()
        self.assertEqual(rows["account_median"]["normalized_result"], 30)
        self.assertEqual(rows["baseline_ratio"]["normalized_result"], 4)
        self.assertAlmostEqual(rows["log_ratio"]["normalized_result"], 1.3862943611)
        self.assertEqual(rows["percentile"]["normalized_result"], 100)
        self.assertEqual(rows["age_matched_percentile"]["normalized_result"], 100)
        self.assertTrue(rows["robust_deviation"]["eligible"])
        self.assertEqual(rows["baseline_ratio"]["sample_size"], 5)

    def test_null_and_missing_metrics_are_unknown(self):
        for target in (video("null", None), video("other", 3, metric="likes")):
            rows = self.results(target=target)
            self.assertTrue(all(not row["eligible"] and row["normalized_result"] is None
                                for row in rows.values()))

    def test_paid_and_other_platform_or_definition_excluded(self):
        bad = [video("paid", 100, exposure="paid"), video("tiktok", 100, platform="tiktok")]
        changed = copy.deepcopy(self.cohort[0].model_dump())
        changed["source"]["reference"] = "other-definition"
        changed["source"]["provider_identifier"] = "other-definition"
        changed["performance"]["metric_definitions"]["views"]["measurement_basis"] = "different"
        bad.append(BenchmarkVideo.model_validate(changed))
        rows = self.results(peers=bad)
        self.assertFalse(rows["baseline_ratio"]["eligible"])
        self.assertEqual(rows["baseline_ratio"]["sample_size"], 0)

    def test_small_sample_and_duplicate_source(self):
        self.assertFalse(self.results(peers=self.cohort[:2])["percentile"]["eligible"])
        repeated = [video(f"copy-{i}", 10, source="same-source") for i in range(8)]
        row = self.results(peers=repeated)["percentile"]
        self.assertEqual(row["sample_size"], 1)
        self.assertFalse(row["eligible"])

    def test_zero_baseline_and_age_window(self):
        zeros = [video(f"zero-{i}", 0, age=30) for i in range(5)]
        rows = self.results(peers=zeros)
        self.assertFalse(rows["baseline_ratio"]["eligible"])
        self.assertFalse(rows["age_matched_percentile"]["eligible"])

    def test_harness_emits_methods_without_universal_score(self):
        videos = [self.target, *self.cohort]
        payload = {"videos": [item.model_dump(mode="json") for item in videos],
                   "requests": [{"target": "target", "metric": "views"}]}
        rows = run(payload)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all("method" in row and "reason" in row and "sample_size" in row
                            and "viral_score" not in row and "score" not in row for row in rows))

    def test_precomputed_baseline_is_distinct_and_carries_context(self):
        target = with_baseline(self.target)
        rows = {row["method"]: row for row in evaluate_baseline(target, "views", baseline_context())}
        self.assertEqual(set(rows), {"account_median", "baseline_ratio", "log_ratio"})
        self.assertEqual(rows["baseline_ratio"]["normalized_result"], 4)
        self.assertEqual(rows["baseline_ratio"]["sample_size"], 20)
        self.assertEqual(rows["baseline_ratio"]["cohort_identity"]["baseline_source"], "creator-a export")
        self.assertEqual(rows["baseline_ratio"]["source_context"]["metric_definition"]["unit"], "count")
        self.assertEqual(rows["baseline_ratio"]["comparison_context"]["method_reference"], "median")
        self.assertTrue(any("Declared format is unknown" in note for note in rows["baseline_ratio"]["limitations"]))
        payload = {"videos": [target.model_dump(mode="json")], "requests": [
            {"target": "target", "metric": "views", "comparison": "account_baseline",
             "baseline_context": baseline_context()}]}
        self.assertEqual(len(run(payload)), 3)

    def test_baseline_known_conflicts_and_unknown_context_are_ineligible(self):
        target = with_baseline(self.target)
        for context, phrase in (
            (baseline_context(exposure="paid"), "exposure mismatch"),
            (baseline_context(platform="facebook"), "platform mismatch"),
            (baseline_context(account_identifier="creator-b"), "account_identifier mismatch"),
            (baseline_context(publication_age_min_days=20, publication_age_max_days=25),
             "publication age mismatch"),
            (baseline_context(target_excluded=False), "target exclusion"),
            (None, "context unavailable"),
            (baseline_context(exposure=None), "exposure unknown"),
        ):
            with self.subTest(context=context):
                rows = evaluate_baseline(target, "views", context)
                self.assertTrue(all(not row["eligible"] and phrase in row["reason"] for row in rows))
        self.assertFalse(evaluate_baseline(with_baseline(self.target, method="mean"), "views",
                                            baseline_context())[0]["eligible"])

    def test_peer_conflicts_and_unknown_window_are_explicit(self):
        bad = [video("paid", 9, exposure="paid"), video("facebook", 9, platform="facebook"),
               video("old", 9, age=30), video("unknown", 9, exposure="unknown")]
        raw = video("no-window", 9).model_dump()
        raw["performance"]["observation_window_start"] = None
        bad.append(BenchmarkVideo.model_validate(raw))
        row = self.results(peers=[*self.cohort, *bad])["baseline_ratio"]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["sample_size"], 5)
        reasons = {item["reference"]: item["reasons"] for item in row["excluded"]}
        self.assertIn("exposure mismatch", reasons["paid"])
        self.assertIn("platform mismatch", reasons["facebook"])
        self.assertIn("publication age mismatch", reasons["old"])
        self.assertIn("exposure unknown or mixed", reasons["unknown"])
        self.assertIn("explicit publication-to-fetch observation window", reasons["no-window"])
        target_raw = self.target.model_dump()
        target_raw["performance"]["observation_window_start"] = None
        blocked = self.results(target=BenchmarkVideo.model_validate(target_raw))
        self.assertTrue(all(not item["eligible"] for item in blocked.values()))

    def test_duplicate_id_url_and_target_alias_do_not_inflate_cohort(self):
        first = video("first", 10, source="shared-id").model_dump()
        first["source"]["public_url"] = "https://example.test/shared"
        alias = video("alias", 20).model_dump()
        alias["source"]["provider_identifier"] = None
        alias["source"]["public_url"] = "https://example.test/shared"
        row = self.results(peers=[*self.cohort[:4], BenchmarkVideo.model_validate(first),
                                  BenchmarkVideo.model_validate(alias)])["percentile"]
        self.assertEqual(row["sample_size"], 5)
        self.assertEqual(row["comparison_context"]["deduplicated_records"], 1)
        target_alias = self.target.model_dump()
        target_alias["source"]["provider_identifier"] = None
        target_alias["source"]["public_url"] = "https://example.test/target"
        target_with_url = self.target.model_dump()
        target_with_url["source"]["public_url"] = "https://example.test/target"
        peers = [*self.cohort, BenchmarkVideo.model_validate(target_with_url),
                 BenchmarkVideo.model_validate(target_alias)]
        row = self.results(peers=peers)["percentile"]
        self.assertEqual(row["sample_size"], 5)

    def test_dedup_uses_eligible_snapshot_and_does_not_invent_identity(self):
        eligible = video("eligible", 10, source="same-id")
        newer = eligible.model_dump()
        newer["source"]["reference"] = "newer-paid"
        newer["performance"]["exposure"] = "paid"
        newer["performance"]["fetched_at"] = NOW + timedelta(hours=1)
        peers = [*self.cohort[:4], eligible, BenchmarkVideo.model_validate(newer)]
        row = self.results(peers=peers)["baseline_ratio"]
        self.assertTrue(row["eligible"])
        self.assertEqual(row["sample_size"], 5)
        self.assertIn("eligible", row["cohort"])
        self.assertTrue(any(item["reference"] == "newer-paid" for item in row["excluded"]))

        # Similar research labels are not source provenance. Distinct IDs remain distinct.
        two = [video("shared-label", 10, source="id-a"),
               video("shared-label", 20, source="id-b")]
        distinct = self.results(peers=two)["percentile"]
        self.assertEqual(distinct["sample_size"], 2)


if __name__ == "__main__":
    unittest.main()
