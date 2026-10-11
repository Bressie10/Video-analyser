"""Focused checks for offline low-level motion evidence and audit accounting."""

import json
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.stage4_3_motion import (
    VARIANTS, attach_event_descriptors, audit, cut_masked_samples, flow_descriptors, replay_descriptors,
    simplified_events,
)
from intelligence.evaluation.stage4_motion import _interval_stats


EVALUATION = Path(__file__).resolve().parents[1] / "intelligence" / "evaluation"
RESULT = EVALUATION / "stage4_3" / "motion_contract_experiment.json"


class Stage43MotionTests(unittest.TestCase):
    def test_numeric_descriptors_measure_local_and_global_fields(self):
        import numpy as np

        local = np.zeros((10, 10, 2), dtype=np.float32)
        local[2:4, 2:4, 0] = 2
        local_row = flow_descriptors(local)
        self.assertAlmostEqual(local_row["active_pixel_coverage"], 0.04)
        self.assertAlmostEqual(local_row["mean_flow_magnitude"], 0.08)
        self.assertAlmostEqual(local_row["median_global_vector_magnitude"], 2.0)
        self.assertAlmostEqual(local_row["coherence"], 1.0)

        global_flow = np.zeros((10, 10, 2), dtype=np.float32)
        global_flow[:, :, 0] = 2
        global_row = flow_descriptors(global_flow)
        self.assertEqual(global_row["active_pixel_coverage"], 1.0)
        self.assertAlmostEqual(global_row["coherence"], 1.0)
        empty = flow_descriptors(np.zeros((10, 10, 2), dtype=np.float32))
        self.assertIsNone(empty["coherence"])

    def test_known_clip_replays_classification_and_descriptors(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "four_frames.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, (32, 32))
            self.assertTrue(writer.isOpened())
            for offset in range(4):
                frame = np.zeros((32, 32, 3), dtype=np.uint8)
                frame[8:16, 4 + offset:12 + offset] = 255
                writer.write(frame)
            writer.release()
            # A first pass yields the expected raw stream; the replay must match it exactly.
            from intelligence.evaluation.stage4_motion import sample_video
            expected, _, _ = sample_video(path)
            samples, duration, sampling = replay_descriptors(path, expected)
            with self.assertRaisesRegex(ValueError, "classifier drift"):
                replay_descriptors(path, [{**row, "confidence": -1} for row in expected])
        self.assertEqual(len(samples), 3)
        self.assertAlmostEqual(duration, 0.5)
        self.assertAlmostEqual(sampling["sample_interval_seconds"], 0.125)
        self.assertTrue(all(row["mean_flow_magnitude"] >= 0 for row in samples))

    def test_cut_cells_stay_gaps_and_no_semantic_camera_labels_escape(self):
        base = [
            {"timestamp": 0.125, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8},
            {"timestamp": 0.25, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8},
            {"timestamp": 0.375, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8},
        ]
        scene = [{"timestamp": row["timestamp"], "skipped_scene_cuts": [0.2] if index == 1 else []}
                 for index, row in enumerate(base)]
        masked = cut_masked_samples(base, scene)
        events = simplified_events(masked, 0.5, 0.125)
        self.assertEqual([row["type"] for row in events], ["motion_present", "motion_present"])
        self.assertEqual([(row["start"], row["end"]) for row in events],
                         [(0.0, 0.125), (0.25, 0.5)])
        self.assertEqual(_interval_stats(events)[1], 0)

    def test_local_requires_original_local_evidence(self):
        samples = [
            {"timestamp": 0.125, "type": "local_motion", "confidence": 0.7,
             "active_pixel_coverage": 0.2, "skipped_scene_cuts": []},
            {"timestamp": 0.25, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8, "skipped_scene_cuts": []},
            {"timestamp": 0.375, "type": "local_motion", "confidence": 0.7,
             "active_pixel_coverage": 0.2, "skipped_scene_cuts": []},
        ]
        events = simplified_events(samples, 0.5, 0.125)
        self.assertEqual([row["type"] for row in events],
                         ["local_motion", "motion_present", "local_motion"])

    def test_suppression_does_not_invent_flow_in_null_cell(self):
        samples = [
            {"timestamp": 0.125, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8, "skipped_scene_cuts": []},
            {"timestamp": 0.25, "type": None, "confidence": 0.0,
             "active_pixel_coverage": 0.0, "skipped_scene_cuts": []},
            {"timestamp": 0.375, "type": "camera_pan", "confidence": 0.7,
             "active_pixel_coverage": 0.8, "skipped_scene_cuts": []},
        ]
        events = simplified_events(samples, 0.5, 0.125)
        self.assertEqual([(row["start"], row["end"]) for row in events],
                         [(0.0, 0.125), (0.25, 0.5)])

    def test_saved_pilot_invariants_and_audit_denominators(self):
        data = json.loads(RESULT.read_text())
        self.assertEqual(len(data["sources"]), 11)
        self.assertEqual(data["audit"]["reviewed_count"], 54)
        self.assertEqual(data["audit"]["valid_count"], 38)
        self.assertEqual(data["audit"]["no_meaningful_count"], 15)
        self.assertEqual(data["audit"]["uncertain_count"], 1)
        for source in data["sources"].values():
            for name in VARIANTS[1:]:
                self.assertAlmostEqual(_interval_stats(source["events"][name])[1], 0)
            for name in VARIANTS[3:]:
                self.assertLessEqual({row["type"] for row in source["events"][name]},
                                     {"motion_present", "local_motion"})
                self.assertTrue(all(row["sample_count"] > 0 and "confidence" not in row
                                    for row in source["events"][name]))
                self.assertTrue(all(row["mean_flow_magnitude"] is not None
                                    for row in source["events"][name]))
            self.assertEqual(source["skipped_flow_pairs"],
                             sum(row["cut_crossing_excluded"] for row in source["samples"]))
            raw = [{key: value for key, value in row.items()
                    if key not in ("cut_crossing_excluded", "scene_reset_type")}
                   for row in source["samples"]]
            scene = [{"timestamp": row["timestamp"],
                      "skipped_scene_cuts": [row["timestamp"]] if row["cut_crossing_excluded"] else []}
                     for row in source["samples"]]
            masked = cut_masked_samples(raw, scene)
            interval = source["sampling"]["sample_interval_seconds"]
            rebuilt = attach_event_descriptors(
                simplified_events(masked, source["duration_seconds"], interval), masked, interval)
            self.assertEqual(rebuilt, source["events"]["simplified_cut_mask_plus_singleton"])
        for name in VARIANTS:
            self.assertEqual(data["aggregate"][name]["total_events"],
                             sum(len(source["events"][name]) for source in data["sources"].values()))
        video_09 = [row for row in data["audit"]["records"] if row["source_ref"] == "09"]
        self.assertEqual(len(video_09), 4)
        self.assertTrue(all(not row["survival"]["simplified_scene_reset_plus_singleton"]["any_event"]
                            for row in video_09))
        self.assertTrue(all(source["events"][VARIANTS[3]] == source["events"][VARIANTS[4]]
                            for source in data["sources"].values()))
        self.assertEqual(data["recommendation"]["choice"], "B")

    def test_audit_precision_counts_exclude_uncertain(self):
        records = [
            {"audit_id": "one", "source_ref": "01", "detector_class": "local_motion",
             "reviewed_class": "local_subject_motion", "raw_class_support_interval_seconds": [0, 0.125]},
            {"audit_id": "two", "source_ref": "01", "detector_class": "unknown",
             "reviewed_class": "no_meaningful_motion", "raw_class_support_interval_seconds": [0.125, 0.25]},
            {"audit_id": "three", "source_ref": "01", "detector_class": "unknown",
             "reviewed_class": "uncertain", "raw_class_support_interval_seconds": [0.25, 0.375]},
        ]
        events = [{"start": 0, "end": 0.125, "type": "local_motion"},
                  {"start": 0.125, "end": 0.25, "type": "motion_present"}]
        sources = {"01": {"production_scene_cuts_seconds": [0.2],
                          "events": {name: events for name in VARIANTS}}}
        result = audit(records, sources)["summary"][VARIANTS[-1]]
        self.assertEqual(result["meaningful_motion_presence"]["precision"], 0.5)
        self.assertEqual(result["meaningful_motion_presence"]["recall"], 1.0)
        self.assertEqual(result["local_motion"]["precision"], 1.0)
        self.assertEqual(result["cut_associated_no_motion_retained"], 1)


if __name__ == "__main__":
    unittest.main()
