"""Focused tests for offline motion stabilization and interval metrics."""

import unittest

from intelligence.evaluation.stage4_motion import (
    CONFIGS, _interval_stats, baseline_events, configurations, metrics,
    runs_to_events, suppress_singletons,
)


def sample(timestamp, kind, confidence=0.6):
    return {"timestamp": timestamp, "type": kind, "confidence": confidence}


class Stage4MotionTests(unittest.TestCase):
    def test_baseline_reproduces_transition_overlap_and_confidence(self):
        raw = [sample(0.125, "camera_pan", 0.8), sample(0.25, "camera_pan", 0.6),
               sample(0.375, "unknown", 0.4), sample(0.5, None, 0)]
        events = baseline_events(raw, 0.5, 0.125)
        self.assertEqual(events, [
            {"start": 0.0, "end": 0.375, "type": "camera_pan", "confidence": 0.7},
            {"start": 0.25, "end": 0.5, "type": "unknown", "confidence": 0.4},
        ])
        self.assertAlmostEqual(_interval_stats(events)[1], 0.125)

    def test_corrected_configs_never_overlap_exclusive_states(self):
        raw = [sample(0.125, "camera_pan"), sample(0.25, "unknown"),
               sample(0.375, "camera_pan"), sample(0.5, "camera_zoom"),
               sample(0.625, None, 0), sample(0.75, "local_motion")]
        variants = configurations(raw, 0.875, 0.125)
        self.assertEqual(tuple(variants), CONFIGS)
        for name, events in variants.items():
            if name != "baseline":
                self.assertEqual(_interval_stats(events)[1], 0, name)
        self.assertEqual(variants["nonoverlap_only"][1]["start"], 0.25)
        self.assertEqual([event["type"] for event in variants["short_run_suppression"]],
                         ["camera_pan", "camera_zoom", "local_motion"])

    def test_singleton_uses_original_neighbors_and_preserves_confidence(self):
        raw = [sample(0.125, "camera_pan"), sample(0.25, "unknown", 0.2),
               sample(0.375, "camera_pan"), sample(0.5, "unknown"),
               sample(0.625, "camera_pan")]
        stable = suppress_singletons(raw)
        self.assertEqual([item["type"] for item in stable],
                         ["camera_pan", "camera_pan", "camera_pan", "camera_pan", "camera_pan"])
        self.assertEqual(stable[1]["confidence"], 0.2)
        self.assertEqual(raw[1]["type"], "unknown")

    def test_minimum_duration_discards_short_runs_without_bridging(self):
        raw = [sample(0.125, "camera_pan"), sample(0.25, "camera_pan"),
               sample(0.375, "unknown"), sample(0.5, "camera_zoom"),
               sample(0.625, "camera_zoom")]
        events = runs_to_events(raw, 0.625, 0.125, min_duration=0.25,
                                unknown_gap=True)
        self.assertEqual([(event["start"], event["end"], event["type"])
                          for event in events],
                         [(0.0, 0.25, "camera_pan"), (0.375, 0.625, "camera_zoom")])
        self.assertEqual(metrics(events, 0.625)["video_covered_percent"], 80)

    def test_final_run_extends_to_duration_and_empty_metrics(self):
        event = runs_to_events([sample(0.125, "unknown")], 0.3, 0.125)[0]
        self.assertEqual((event["start"], event["end"]), (0.0, 0.3))
        self.assertEqual(metrics([], 1)["median_event_duration_seconds"], None)
        self.assertEqual(metrics([], 1)["counts_by_type"]["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
