"""Focused temporal OCR grouping checks without loading the OCR model."""

import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.video_processing import _consolidate_ocr_observations, detect_on_screen_text


def detection(text, confidence=0.9, left=10, top=20, width=120):
    return {
        "text": text,
        "confidence": confidence,
        "bounding_box": [
            [left, top], [left + width, top],
            [left + width, top + 30], [left, top + 30],
        ],
    }


def sample(time, *detections):
    return {"timestamp_seconds": time, "detections": list(detections)}


class OcrConsolidationTests(unittest.TestCase):
    def consolidate(self, observations, duration=2.0):
        original = copy.deepcopy(observations)
        result = _consolidate_ocr_observations(observations, duration, 0.5)
        self.assertEqual(observations, original)  # raw observations remain intact
        return result

    def test_repeated_caption_is_one_span_with_best_detection(self):
        spans = self.consolidate([
            sample(0, detection("WATCH NOW", 0.76)),
            sample(0.5, detection("Watch now", 0.94, left=13)),
            sample(1, detection("watch now", 0.85, left=16)),
            sample(1.5),
        ])
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["text"], "Watch now")
        self.assertEqual(spans[0]["confidence"], 0.94)
        self.assertEqual(spans[0]["appearance_timestamp_seconds"], 0)
        self.assertEqual(spans[0]["disappearance_timestamp_seconds"], 1.5)

    def test_small_ocr_typo_merges_but_different_number_does_not(self):
        spans = self.consolidate([
            sample(0, detection("LIMITED OFFER", 0.94), detection("SAVE 10%", 0.9, top=70)),
            sample(0.5, detection("LIMITED OFER", 0.69), detection("SAVE 20%", 0.9, top=70)),
            sample(1),
        ])
        self.assertEqual(len(spans), 3)
        self.assertEqual([(s["text"], s["appearance_timestamp_seconds"]) for s in spans],
                         [("LIMITED OFFER", 0), ("SAVE 10%", 0), ("SAVE 20%", 0.5)])

    def test_moving_text_merges_across_adjacent_frames(self):
        spans = self.consolidate([
            sample(0, detection("A LONG CAPTION", left=10)),
            sample(0.5, detection("A LONG CAPTION", left=42)),
            sample(1, detection("A LONG CAPTION", left=73)),
            sample(1.5),
        ])
        self.assertEqual(len(spans), 1)

    def test_disappearing_and_reappearing_text_forms_two_spans(self):
        spans = self.consolidate([
            sample(0, detection("BACK SOON")), sample(0.5),
            sample(1, detection("BACK SOON")), sample(1.5),
        ])
        self.assertEqual(len(spans), 2)
        self.assertEqual([s["appearance_timestamp_seconds"] for s in spans], [0, 1])

    def test_distinct_nearby_text_remains_separate(self):
        spans = self.consolidate([
            sample(0, detection("SHOP NOW", left=10), detection("SHOW NOW", left=145)),
            sample(0.5, detection("SHOP NOW", left=14), detection("SHOW NOW", left=141)),
            sample(1),
        ])
        self.assertEqual(len(spans), 2)
        self.assertEqual({s["text"] for s in spans}, {"SHOP NOW", "SHOW NOW"})

    def test_high_confidence_word_change_at_same_position_remains_separate(self):
        spans = self.consolidate([
            sample(0, detection("FREE SHIPPING", 0.94)),
            sample(0.5, detection("FREE SHOPPING", 0.95)),
            sample(1),
        ])
        self.assertEqual([span["text"] for span in spans], ["FREE SHIPPING", "FREE SHOPPING"])

    def test_low_confidence_one_frame_noise_is_removed(self):
        spans = self.consolidate([
            sample(0, detection("NOISE", 0.64), detection("CLEAR", 0.93, top=70)),
            sample(0.5),
        ])
        self.assertEqual([span["text"] for span in spans], ["CLEAR"])

    def test_detector_passes_raw_low_confidence_observations_to_consolidator(self):
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.side_effect = [4, 4]
        capture.read.side_effect = [(True, 0), (True, 1), (True, 2), (True, 3), (False, None)]
        box = [[value + 0.25 for value in point] for point in detection("RAW")["bounding_box"]]
        results = [
            SimpleNamespace(boxes=[box], txts=["  RAW  "], scores=[0.54321]),
            SimpleNamespace(boxes=[box], txts=["RAW"], scores=[0.91]),
        ]
        with (
            patch("cv2.VideoCapture", return_value=capture),
            patch("app.video_processing._ocr_model", return_value=Mock(side_effect=results)),
            patch("app.video_processing._consolidate_ocr_observations", wraps=_consolidate_ocr_observations) as group,
        ):
            spans = detect_on_screen_text(Path("fixture.mp4"))
        raw = group.call_args.args[0]
        self.assertEqual(raw[0]["detections"][0]["text"], "  RAW  ")
        self.assertEqual(raw[0]["detections"][0]["confidence"], 0.54321)
        self.assertEqual(raw[0]["detections"][0]["bounding_box"][0], [10.25, 20.25])
        self.assertEqual([span["text"] for span in spans], ["RAW"])
        self.assertEqual(spans[0]["bounding_box"][0], [10, 20])
        capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
