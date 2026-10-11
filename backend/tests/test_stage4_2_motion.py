"""Focused tests for scene-aware optical-flow reset and pilot audit accounting."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligence.evaluation.stage4_2_motion import (
    VARIANTS, crossed_cuts, overlaps, scene_aware_samples,
    suppress_preserving_scene_gaps,
)
from intelligence.evaluation.stage4_motion import _interval_stats, runs_to_events


EVALUATION = Path(__file__).resolve().parents[1] / "intelligence" / "evaluation"
RESULT_PATH = EVALUATION / "stage4_2" / "scene_aware_motion.json"
STAGE4 = json.loads((EVALUATION / "stage4" / "motion_stabilization.json").read_text())
AUDIT = json.loads((EVALUATION / "stage4_1" / "motion_classification_audit.json").read_text())


class Stage42MotionTests(unittest.TestCase):
    def test_cut_pair_rule(self):
        self.assertEqual(crossed_cuts([0.25, 0.5], 0.125, 0.25), [0.25])
        self.assertEqual(crossed_cuts([0.25, 0.5], 0.25, 0.375), [])
        self.assertEqual(crossed_cuts([0.25, 0.5], 0.125, 0.5), [0.25, 0.5])

    def test_flow_pair_is_skipped_and_history_reset_on_known_clip(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "four_frames.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, (32, 32))
            self.assertTrue(writer.isOpened())
            for index in range(4):
                writer.write(np.full((32, 32, 3), 20 + index * 20, dtype=np.uint8))
            writer.release()
            histories = []

            def classify(_flow, history):
                histories.append(len(history))
                history.append("direction")
                return "camera_pan", 0.7, None

            with patch("app.video_processing._classify_optical_flow", side_effect=classify):
                samples, duration, sampling = scene_aware_samples(path, [0.25])

        self.assertEqual([round(item["timestamp"], 3) for item in samples],
                         [0.125, 0.25, 0.375])
        self.assertEqual([item["type"] for item in samples],
                         ["camera_pan", None, "camera_pan"])
        self.assertEqual(samples[1]["skipped_scene_cuts"], [0.25])
        self.assertEqual(histories, [0, 0])
        events = runs_to_events(samples, duration, sampling["sample_interval_seconds"])
        self.assertEqual([(item["start"], item["end"]) for item in events],
                         [(0.0, 0.125), (0.25, 0.5)])
        self.assertEqual(_interval_stats(events)[1], 0)

    def test_singleton_suppression_cannot_bridge_a_cut(self):
        samples = [
            {"timestamp": 0.125, "type": "camera_pan", "confidence": 0.8, "skipped_scene_cuts": []},
            {"timestamp": 0.25, "type": None, "confidence": 0.0, "skipped_scene_cuts": [0.2]},
            {"timestamp": 0.375, "type": "camera_pan", "confidence": 0.8, "skipped_scene_cuts": []},
        ]
        stable = suppress_preserving_scene_gaps(samples)
        self.assertEqual([item["type"] for item in stable], ["camera_pan", None, "camera_pan"])
        self.assertEqual(len(runs_to_events(stable, 0.5, 0.125)), 2)

    def test_stage4_comparators_and_all_four_video09_records(self):
        result = json.loads(RESULT_PATH.read_text())
        self.assertEqual(result["scene_signal"]["threshold"], 27.0)
        self.assertFalse(result["scene_signal"]["repaired_truth_used_for_output"])
        self.assertEqual(set(result["aggregate"]), set(VARIANTS))
        self.assertTrue(all(source["production_scene_output_reproduced"]
                            for source in result["sources"].values()))
        for ref, source in result["sources"].items():
            self.assertEqual(source["events"]["nonoverlap_only"],
                             STAGE4["sources"][ref]["events"]["nonoverlap_only"])
            self.assertEqual(source["events"]["one_sample_suppression_only"],
                             STAGE4["sources"][ref]["events"]["short_run_suppression"])
            for name in VARIANTS:
                self.assertEqual(_interval_stats(source["events"][name])[1], 0)
                self.assertEqual(source["metrics"][name]["total_events"],
                                 len(source["events"][name]))
        for name in VARIANTS:
            self.assertEqual(result["aggregate"][name]["total_events"],
                             sum(source["metrics"][name]["total_events"]
                                 for source in result["sources"].values()))
            self.assertGreater(result["aggregate"][name]["counts_by_type"]["unknown"], 0)
        reviewed_09 = [row for row in result["audit"]["records"] if row["source_ref"] == "09"]
        self.assertEqual(len(reviewed_09), 4)
        self.assertEqual({row["audit_id"] for row in reviewed_09},
                         {row["audit_id"] for row in AUDIT["records"] if row["source_ref"] == "09"})
        for row in reviewed_09:
            self.assertTrue(row["production_scene_cuts_on_support"])
            self.assertFalse(row["survival"]["scene_aware_reset_only"]["any_event"])
            self.assertFalse(row["survival"]["scene_aware_reset_plus_suppression"]["any_event"])

    def test_audit_survival_is_measured_on_raw_support(self):
        result = json.loads(RESULT_PATH.read_text())
        for row in result["audit"]["records"]:
            interval = row["raw_class_support_interval_seconds"]
            for name in VARIANTS:
                events = result["sources"][row["source_ref"]]["events"][name]
                self.assertEqual(row["survival"][name]["same_class"],
                                 any(event["type"] == row["detector_class"] and overlaps(interval, event)
                                     for event in events))
                self.assertEqual(row["survival"][name]["any_event"],
                                 any(overlaps(interval, event) for event in events))
        attribution = result["audit"]["cut_attribution"]
        self.assertEqual(attribution["semantic_failures_in_reviewed_sample"], 36)
        self.assertEqual(attribution["semantic_failures_with_production_cut_on_raw_support"], 10)
        self.assertNotIn("/private/tmp", RESULT_PATH.read_text())


if __name__ == "__main__":
    unittest.main()
