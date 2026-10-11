"""Validate the committed, media-free Stage 4.1 audit against Stage 4 samples."""

import json
import statistics
import unittest
from collections import Counter
from pathlib import Path


EVALUATION = Path(__file__).resolve().parents[1] / "intelligence" / "evaluation"
AUDIT = json.loads((EVALUATION / "stage4_1" / "motion_classification_audit.json").read_text())
STAGE4 = json.loads((EVALUATION / "stage4" / "motion_stabilization.json").read_text())
CONFIGS = ("nonoverlap_only", "short_run_suppression", "min_0.5", "unknown_as_gap")
LABELS = ("camera_pan", "camera_zoom", "camera_shake", "local_subject_motion",
          "general_scene_motion", "no_meaningful_motion", "uncertain")


def overlaps(interval, event):
    return min(interval[1], event["end"]) - max(interval[0], event["start"]) > 0.001


class Stage41MotionAuditTests(unittest.TestCase):
    def test_stratification_and_review_provenance(self):
        rows = AUDIT["records"]
        self.assertEqual(len(rows), 54)
        self.assertEqual(len({row["audit_id"] for row in rows}), 54)
        self.assertEqual(Counter(row["detector_class"] for row in rows),
                         {kind: 9 for kind in STAGE4["sources"]["04"]["metrics"]["baseline"]["counts_by_type"]})
        self.assertEqual(sum(row["source_ref"] == "09" for row in rows), 4)
        self.assertTrue({"04", "07", "09", "12"}.issubset({row["source_ref"] for row in rows}))
        self.assertFalse(AUDIT["review_context"]["media_in_git"])
        self.assertTrue(all(row["reviewed_class"] in LABELS and row["review_note"] for row in rows))

    def test_each_record_matches_stage4_baseline_and_raw_support(self):
        for row in AUDIT["records"]:
            source = STAGE4["sources"][row["source_ref"]]
            event = source["events"]["baseline"][row["baseline_event_index"]]
            self.assertEqual([event["start"], event["end"]], row["interval_seconds"])
            self.assertEqual((event["type"], event["confidence"]),
                             (row["detector_class"], row["detector_confidence"]))
            support = row["raw_class_support_interval_seconds"]
            self.assertLess(support[0], support[1])
            self.assertGreaterEqual(support[0], event["start"] - 0.001)
            self.assertLessEqual(support[1], event["end"] + 0.001)
            self.assertTrue(any(sample["type"] == event["type"] and
                                support[0] < sample["timestamp"] <= support[1] + 0.001
                                for sample in source["raw_samples"]))
            for name in CONFIGS:
                events = source["events"][name]
                same = any(candidate["type"] == event["type"] and overlaps(support, candidate)
                           for candidate in events)
                any_event = any(overlaps(support, candidate) for candidate in events)
                self.assertEqual(row["survives_same_detector_class"][name], same)
                self.assertEqual(row["survives_any_emitted_event"][name], any_event)
                self.assertFalse(same and not any_event)

    def test_confusion_precision_and_stabilization_totals(self):
        rows = AUDIT["records"]
        for prediction, cells in AUDIT["confusion_matrix"].items():
            self.assertEqual(sum(cells.values()), 9)
            for label in LABELS:
                self.assertEqual(cells[label], sum(row["detector_class"] == prediction and
                                                   row["reviewed_class"] == label for row in rows))
        targets = {"camera_pan": "camera_pan", "camera_zoom": "camera_zoom",
                   "camera_shake": "camera_shake", "local_motion": "local_subject_motion",
                   "general_motion": "general_scene_motion"}
        correct_confidences = []
        incorrect_confidences = []
        for prediction, target in targets.items():
            determinate = [row for row in rows if row["detector_class"] == prediction and
                           row["reviewed_class"] != "uncertain"]
            correct = [row for row in determinate if row["reviewed_class"] == target]
            self.assertEqual(AUDIT["precision_by_detector_class"][prediction]["correct"], len(correct))
            self.assertEqual(AUDIT["precision_by_detector_class"][prediction]["sample_precision"],
                             len(correct) / len(determinate))
            correct_confidences.extend(row["detector_confidence"] for row in correct)
            incorrect_confidences.extend(row["detector_confidence"] for row in determinate if row not in correct)
        self.assertEqual(AUDIT["confidence"]["correct_semantic_predictions"]["mean"],
                         statistics.mean(correct_confidences))
        self.assertEqual(AUDIT["confidence"]["incorrect_semantic_predictions"]["mean"],
                         statistics.mean(incorrect_confidences))
        valid = [row for row in rows if row["reviewed_class"] not in
                 ("uncertain", "no_meaningful_motion")]
        noise = [row for row in rows if row["reviewed_class"] == "no_meaningful_motion"]
        for name in CONFIGS:
            values = AUDIT["stabilization"][name]
            self.assertEqual(values["visually_valid_total"], len(valid))
            self.assertEqual(values["obvious_noise_total"], len(noise))
            self.assertEqual(values["valid_same_class_on_raw_support"],
                             sum(row["survives_same_detector_class"][name] for row in valid))
            self.assertEqual(values["valid_any_event_on_raw_support"],
                             sum(row["survives_any_emitted_event"][name] for row in valid))
            self.assertEqual(values["noise_no_event_on_raw_support"],
                             sum(not row["survives_any_emitted_event"][name] for row in noise))
        self.assertNotIn("/private/tmp", json.dumps(AUDIT))
        self.assertNotIn(".jpg", json.dumps(AUDIT))

    def test_video09_events_are_isolated_edit_samples(self):
        self.assertEqual(len(AUDIT["video_09"]), 4)
        for row in AUDIT["video_09"]:
            self.assertEqual(len(row["sample_timestamps_seconds"]), 1)
            self.assertIsNone(row["preceding_type"])
            self.assertIsNone(row["following_type"])
            self.assertEqual(row["reviewed_class"], "no_meaningful_motion")
            self.assertFalse(row["survives_short_run_suppression"])


if __name__ == "__main__":
    unittest.main()
