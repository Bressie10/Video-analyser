import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligence.evaluation.stage3_scene import _summary, evaluate, markdown


class SceneSweepTest(unittest.TestCase):
    def test_summary_pools_matched_errors_and_preserves_empty_reference(self):
        rows = [
            {"tp": 1, "fp": 1, "fn": 1, "timing_errors_seconds": [0.2]},
            {"tp": 0, "fp": 2, "fn": 0, "timing_errors_seconds": []},
        ]
        summary = _summary(rows)
        self.assertEqual((summary["tp"], summary["fp"], summary["fn"], summary["predicted_cuts"]),
                         (1, 3, 1, 4))
        self.assertEqual(summary["mean_matched_timing_error_seconds"], 0.2)

    def test_scene_only_sweep_and_baseline_guard(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            media = root / "clip.mp4"
            media.write_bytes(b"test clip")
            truth_dir, baseline_dir = root / "truth", root / "baseline"
            truth_dir.mkdir()
            baseline_dir.mkdir()
            from intelligence.evaluation.stage1 import _hash
            manifest = {"schema_version": 1, "sources": [{
                "source_ref": "09", "media_path": str(media), "duration_seconds": 10,
                "creator_ref": None, "rights_note": "test", "annotation_status": "reviewed",
                "partition": "test", "group_ref": "test", "low_level_truth_available": True,
                "variation": [],
            }]}
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            truth = {"low_level_truth_version": "1.0.0", "source_ref": "09",
                     "record_kind": "reviewed", "reviewer_ref": "test", "reviewed_at": "2026-10-10T00:00:00Z",
                     "coverage": {signal: "unavailable" for signal in
                                  ("scene_boundaries", "ocr", "transcript", "motion", "metadata")},
                     "observations": {"scene_boundaries": []}}
            truth["coverage"]["scene_boundaries"] = "complete"
            (truth_dir / "09.json").write_text(json.dumps(truth))
            baseline = {"source_ref": "09", "input_sha256": _hash(media),
                        "analysis": {"scenes": [{"cut_timestamp_seconds": None},
                                                {"cut_timestamp_seconds": 2.0}]}}
            (baseline_dir / "09.json").write_text(json.dumps(baseline))
            calls = []

            def normalise(source, target):
                calls.append("normalise")
                target.write_bytes(source.read_bytes())

            def detector(path, threshold):
                calls.append(threshold)
                return [{"cut_timestamp_seconds": 2.0}] if threshold == 27 else []

            with patch("intelligence.evaluation.stage3_scene.load_manifest", return_value=manifest):
                report = evaluate(manifest_path, truth_dir, baseline_dir,
                                  normalise=normalise, detector=detector)
                self.assertEqual(report["aggregate"]["27"]["0.5"]["fp"], 1)
                self.assertIsNone(report["sources"]["09"]["thresholds"]["27"]["scores"]["0.5"]["f1"])
                self.assertIn("**09**", markdown(report))
                self.assertEqual(calls, ["normalise", 20, 24, 27, 30, 33, 36, 40, 45])
                with self.assertRaisesRegex(ValueError, "does not reproduce"):
                    evaluate(manifest_path, truth_dir, baseline_dir, normalise=normalise,
                             detector=lambda path, threshold: [])


if __name__ == "__main__":
    unittest.main()
