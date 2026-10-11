import copy
import unittest

from intelligence.evaluation.stage3_2_report import render


def _report():
    score = {"tp": 1, "fp": 1, "fn": 0, "precision": 0.5, "recall": 1.0,
             "f1": 2 / 3, "timing_errors_seconds": [0.1]}
    aggregate = score | {"predicted_cuts": 2, "mean_matched_timing_error_seconds": 0.1}
    return {"detector": {"class": "ContentDetector", "version": "0.7.1",
                         "thresholds": [27]},
            "sources": {ref: {"source_sha256": ref, "reference_cuts": 1,
                              "thresholds": {"27": {"predicted_cuts": 2,
                                                     "scores": {tol: score for tol in ("0.1", "0.25", "0.5")}}}}
                        for ref in ("04", "07", "09")},
            "aggregate": {"27": {tol: aggregate for tol in ("0.1", "0.25", "0.5")}},
            "ranked_thresholds_by_0.5s_f1": [27]}


class SceneRepairReportTest(unittest.TestCase):
    def test_renders_comparison_and_rejects_changed_predictions(self):
        old = _report()
        new = copy.deepcopy(old)
        new["sources"]["09"]["reference_cuts"] = 4
        output = render(old, new)
        self.assertIn("not fully blinded independent ground truth", output)
        self.assertIn("Threshold 27 before and after", output)
        self.assertIn("### ±0.25 s", output)
        new["sources"]["09"]["thresholds"]["27"]["predicted_cuts"] = 3
        with self.assertRaisesRegex(ValueError, "Prediction count changed"):
            render(old, new)


if __name__ == "__main__":
    unittest.main()
