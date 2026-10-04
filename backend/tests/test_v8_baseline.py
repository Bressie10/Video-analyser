"""Pure offline checks for V8 observation evaluation."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.v8_baseline import evaluate, evaluate_manifest


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            "metadata": {"duration_seconds": 4.02, "video": {"resolution": {"width": 640}},
                         "audio": {"codec": "aac"}},
            "scenes": [{"cut_timestamp_seconds": None}, {"cut_timestamp_seconds": 2.1},
                       {"cut_timestamp_seconds": 3.0}],
            "on_screen_text": [
                {"text": "Video TEST!", "appearance_timestamp_seconds": 0.5,
                 "disappearance_timestamp_seconds": 2.5},
                {"text": "extra", "appearance_timestamp_seconds": 3.0,
                 "disappearance_timestamp_seconds": 3.5}],
            "audio": {"text": "Hello good world", "segments": [
                {"start": 0.2, "end": 1.2, "text": "Hello good world"}]},
            "motion_events": [{"type": "local_motion", "start_seconds": 1.0, "end_seconds": 2.0},
                              {"type": "camera_pan", "start_seconds": 2.0, "end_seconds": 3.0}],
        }
        self.truth = {
            "metadata": {"duration_seconds": {"value": 4, "tolerance": 0.05},
                         "video.resolution.width": 640, "audio.codec": "aac"},
            "scene_boundaries_seconds": [2.0, 2.2],
            "on_screen_text": [{"text": "video test", "start_seconds": 1.0, "end_seconds": 2.0}],
            "transcript": {"text": "Hello world", "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello good world"}]},
            "motion_events": [{"type": "local_motion", "start_seconds": 1.25,
                               "end_seconds": 2.0},
                              {"type": "camera_zoom", "start_seconds": 2.0,
                               "end_seconds": 3.0}],
        }

    def test_metrics_keep_signals_separate_and_match_once(self):
        output = evaluate(self.analysis, self.truth)
        self.assertEqual(output["scene_boundaries"]["matched"], 1)
        self.assertEqual(output["scene_boundaries"]["precision"], 0.5)
        self.assertEqual(output["scene_boundaries"]["recall"], 0.5)
        self.assertAlmostEqual(output["scene_boundaries"]["mean_absolute_error_seconds"], 0.1)
        self.assertEqual(output["ocr"]["normalized_text"]["recall"], 1)
        self.assertEqual(output["ocr"]["text_and_time"]["precision"], 0.5)
        self.assertEqual(output["ocr"]["text_and_time"]["mean_iou"], 0.5)
        self.assertEqual(output["transcript"]["word_error_rate"], 0.5)
        self.assertAlmostEqual(output["transcript"]["timestamp_mean_absolute_error_seconds"], 0.2)
        self.assertEqual(output["motion_events"]["matched"], 1)
        self.assertEqual(output["motion_events"]["mean_iou"], 0.75)
        self.assertTrue(output["metadata"]["duration_seconds"]["within_tolerance"])

    def test_unaligned_timestamps_and_unchecked_signals_are_not_scored(self):
        self.truth["transcript"]["segments"][0]["text"] = "Hello world"
        output = evaluate(self.analysis, {"transcript": self.truth["transcript"]})
        self.assertEqual(list(output), ["transcript"])
        self.assertIsNone(output["transcript"]["timestamp_mean_absolute_error_seconds"])

    def test_empty_exhaustive_truth_and_bad_tolerances(self):
        output = evaluate(self.analysis, {"scene_boundaries_seconds": [], "motion_events": []})
        self.assertEqual(output["scene_boundaries"]["precision"], 0)
        self.assertIsNone(output["scene_boundaries"]["recall"])
        self.assertEqual(output["motion_events"]["precision"], 0)
        with self.assertRaises(ValueError):
            evaluate(self.analysis, {}, minimum_interval_iou=0)

    def test_manifest_reads_local_json_and_rejects_escape_or_duplicate(self):
        with TemporaryDirectory() as work:
            root = Path(work)
            (root / "analysis.json").write_text(json.dumps(self.analysis))
            (root / "truth.json").write_text(json.dumps(self.truth))
            manifest = root / "manifest.json"
            item = {"id": "synthetic", "analysis": "analysis.json", "truth": "truth.json"}
            manifest.write_text(json.dumps({"schema_version": 1, "fixtures": [item]}))
            self.assertEqual(evaluate_manifest(manifest)["fixtures"]["synthetic"]["ocr"]
                             ["normalized_text"]["matched"], 1)
            manifest.write_text(json.dumps({"schema_version": 1, "fixtures": [item, item]}))
            with self.assertRaisesRegex(ValueError, "Duplicate fixture"):
                evaluate_manifest(manifest)
            item["truth"] = "../truth.json"
            manifest.write_text(json.dumps({"schema_version": 1, "fixtures": [item]}))
            with self.assertRaisesRegex(ValueError, "manifest directory"):
                evaluate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
