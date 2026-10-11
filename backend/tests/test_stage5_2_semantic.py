"""Focused Stage 5.2 selector, OCR, input isolation, and immutable-artifact gates."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.stage5_1_review import structure_covered_runtime_fraction
from intelligence.evaluation.stage5_semantic import (
    SemanticDraft, extract_frames, frame_coverage, model_content, select_frame_timestamps,
    semantic_input, summarize_ocr, validate_draft,
)

EVALUATION = Path(__file__).resolve().parents[1] / "intelligence/evaluation"
IMMUTABLE_DIGESTS = {
    "stage5/pilot": "4daa6005c0c12645b9ce090aee69636693170beb0aea42bafee78b8371da0e20",
    "stage5_1/truth": "200ad176986d5207b3befb488b62d8a3a6429726a1a1d2105f8b1ef638230089",
    "stage5_1/comparisons": "d290c4eaf2f8e0e691988612539576870bb9154d29d2d7c356d2d160c26343fa",
}


class Stage52SemanticTests(unittest.TestCase):
    def test_duration_aware_selection_is_deterministic_bounded_and_covers_long_video(self):
        scenes = [{"start_seconds": i * 2.0, "end_seconds": min(138.5, i * 2.0 + 2.0)}
                  for i in range(69)]
        ocr = [{"start_seconds": i * 3.0, "end_seconds": i * 3.0 + 1.0}
               for i in range(46)]
        long_plan = select_frame_timestamps(138.5, scenes, ocr)
        self.assertEqual(long_plan, select_frame_timestamps(138.5, scenes, ocr))
        self.assertLessEqual(len(long_plan), 32)
        self.assertGreater(len(long_plan), 16)
        self.assertLessEqual(frame_coverage(long_plan, 138.5)["largest_frame_gap_seconds"], 8.0)
        self.assertTrue(any(row["reason"] == "scene_representative" for row in long_plan))
        self.assertTrue(any(row["reason"] == "ocr_change" for row in long_plan))
        short = select_frame_timestamps(28.0, [], [])
        self.assertLessEqual(len(short), 16)
        self.assertLess(len(short), len(long_plan))

    def test_closing_ocr_and_end_card_have_frame_coverage(self):
        ocr = [{"start_seconds": i, "end_seconds": i + 0.5} for i in range(0, 130, 3)]
        ocr += [{"start_seconds": 134.0, "end_seconds": 135.0},
                {"start_seconds": 137.0, "end_seconds": 138.0}]
        plan = select_frame_timestamps(138.5, [], ocr)
        self.assertTrue(any(row["reason"] == "final" and row["timestamp_seconds"] >= 136.0
                            for row in plan))
        self.assertTrue(any(row["reason"] == "ocr_change" and row["timestamp_seconds"] >= 130.0
                            for row in plan))
        self.assertLessEqual(frame_coverage(plan, 138.5)["largest_frame_gap_seconds"], 8.0)

    def test_optional_near_duplicate_scene_frames_are_skipped(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "static.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"),
                                     10.0, (64, 48))
            self.assertTrue(writer.isOpened())
            for _ in range(200):
                writer.write(np.full((48, 64, 3), 100, dtype=np.uint8))
            writer.release()
            scenes = [{"start_seconds": i * 2.0, "end_seconds": i * 2.0 + 2.0}
                      for i in range(10)]
            plan = select_frame_timestamps(20.0, scenes, [])
            frames, _ = extract_frames(video, plan)
            self.assertLess(len(frames), len(plan))
            self.assertFalse(any(row["selection_reason"] == "scene_representative"
                                 for row in frames))
            self.assertTrue(any(row["selection_reason"] == "temporal_coverage"
                                for row in frames))

    def test_ocr_summary_normalizes_and_counts_persistence_without_inventing_text(self):
        rows = [{"ref": "ocr:0", "start_seconds": 0.0, "end_seconds": 2.0,
                 "text": "Take  quiz!"},
                {"ref": "ocr:1", "start_seconds": 1.0, "end_seconds": 3.0,
                 "text": "TAKE QUIZ"},
                {"ref": "ocr:2", "start_seconds": 10.0, "end_seconds": 11.0,
                 "text": "take quiz"}]
        self.assertEqual(summarize_ocr(rows), [{
            "normalized_text": "take quiz", "first_appearance_seconds": 0.0,
            "last_appearance_seconds": 11.0, "approximate_persistence_seconds": 4.0,
            "source_span_count": 3, "repeated_occurrence_count": 2,
            "source_refs": ["ocr:0", "ocr:1", "ocr:2"]}])

    def test_reviewed_truth_performance_motion_and_history_never_enter_model_input(self):
        analysis = {"metadata": {"duration_seconds": 5.0, "video": {"fps": 30,
                    "resolution": {"width": 720, "height": 1280}}},
                    "audio": {"segments": []}, "on_screen_text": [
                        {"appearance_timestamp_seconds": 0.0,
                         "disappearance_timestamp_seconds": 2.0,
                         "text": "Take the quiz"}], "scenes": [],
                    "stage5_1_reviewed_truth": {"secret": "reviewed-answer"},
                    "motion_events": [{"type": "camera_zoom"}],
                    "performance_metrics": {"likes": 999},
                    "company_history": ["private-history"],
                    "previous_recommendations": ["private-recommendation"]}
        content = semantic_input(analysis)
        parts = model_content(content, [{"ref": "frame:0", "timestamp_seconds": 0.1,
                                         "selection_reason": "opening", "jpeg_sha256": "x" * 64,
                                         "_jpeg": b"image"}])
        payload = json.loads(parts[0]["text"])
        self.assertEqual(payload["derived_ocr_summary"][0]["normalized_text"], "take the quiz")
        for excluded in ("stage5_1_reviewed_truth", "reviewed-answer", "motion_events",
                         "camera_zoom", "performance_metrics", "likes", "company_history",
                         "private-history", "previous_recommendations", "private-recommendation"):
            self.assertNotIn(excluded, parts[0]["text"])

    def test_original_stage5_and_stage51_artifacts_are_unchanged(self):
        for directory, expected in IMMUTABLE_DIGESTS.items():
            digest = hashlib.sha256()
            for path in sorted((EVALUATION / directory).iterdir()):
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
            self.assertEqual(digest.hexdigest(), expected)

    def test_frozen_ontology_temporal_support_and_structure_fraction(self):
        content = {"metadata": {"duration_seconds": 10.0}, "transcript": [], "ocr": [],
                   "scenes": [{"ref": "scene:0", "start_seconds": 0.0, "end_seconds": 10.0}]}
        frames = [{"ref": "frame:0", "timestamp_seconds": 5.0}]
        bad = SemanticDraft.model_validate({"findings": [{"technique_id": "visual.not_real",
            "start_seconds": 4.0, "end_seconds": 6.0, "confidence": 0.8,
            "basis": "direct_observation", "rationale": "Claim", "evidence_refs": ["frame:0"]}],
            "structure": [], "uncertainties": []})
        with self.assertRaisesRegex(ValueError, "Unknown technique ID"):
            validate_draft(bad, content, frames)
        bad.findings[0].technique_id = "visual.close_up"
        bad.findings[0].evidence_refs = ["scene:0"]
        with self.assertRaisesRegex(ValueError, "temporally relevant interval support"):
            validate_draft(bad, content, frames)
        bad.findings[0].evidence_refs = ["frame:0"]
        validate_draft(bad, content, frames)
        self.assertEqual(structure_covered_runtime_fraction([
            {"start_seconds": 0, "end_seconds": 4},
            {"start_seconds": 2, "end_seconds": 6}], 10.0), 0.6)


if __name__ == "__main__":
    unittest.main()
