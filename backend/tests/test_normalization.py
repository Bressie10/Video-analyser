"""Synthetic, offline comparisons; no provider data or network access."""

import copy
import unittest
from datetime import datetime, timedelta, timezone

from intelligence.normalization import evaluate
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


if __name__ == "__main__":
    unittest.main()
