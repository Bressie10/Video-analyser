"""Focused checks for provisional semantic review and evaluator boundaries."""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from intelligence.evaluation.stage5_1_review import (
    _flags, _score, compare, one_to_one, validate_truth,
)
from intelligence.evaluation.stage5_semantic import (
    SemanticDraft, evidence_catalog, semantic_input, temporal_evidence_support,
    validate_draft,
)

ROOT = Path(__file__).resolve().parents[1] / "intelligence/evaluation"
HASHES = {
    "01": "47e548bd3f8b6afbd7cf41e96ebef09a80f1b1d42da4551773b6715956111c53",
    "04": "449eb7503768f1d023927a239ae6a187059e60c706155da182252add32a84f1e",
    "08": "c541d98093565263d09e356bc4d0c4bbbd3deca44ec6afbdb5ea7b510bbaa1dd",
    "12": "96aa7654376d660490a6dc0fea601b90d19ca5f3d4ce9fee227826dda96e6167",
}
SUPPORTING_HASHES = {
    "01.md": "0e70fcde6fae852a5908c184512b6bb3ccb1b132c3a3bcc1e8be9758eb34fbb3",
    "01.selection.json": "ff503af9b941c5806df529dba4b14829d48952bd22e67b9d74b9636796d27376",
    "04.md": "de90d6c48cb210fb49db6bca414178171d0b8023efca5c53a2814c12d0052d16",
    "04.selection.json": "834bc6fc1f8603c272d1dd65043f7d7bdf15a0f90a97be50173491587f2453dc",
    "08.md": "721f61d706d0fbefb4a552e34e66b588f21535f4c98979092a5877ef650ba990",
    "08.selection.json": "2c206e191aee7fd77f1af5d4b1e7d8ac385da45bfe3ae9d7c81a72a79e14ea2f",
    "12.md": "257fa5967f114eaeed9aa512b4023e7803d806508159598049d4df9ac2719a56",
    "12.selection.json": "1c04a0bdb5de263a4dadb84ef35533d2757ccd5054976120542d7a2a5f52a1a9",
}


def prediction(label="cta.visual", start=1.0, end=3.0):
    return {"technique_id": label, "start_seconds": start, "end_seconds": end}


def reviewed(label="cta.visual", start=1.0, end=3.0, status="present", coverage="complete"):
    return {**prediction(label, start, end), "status": status, "coverage": coverage}


class Stage51ReviewTests(unittest.TestCase):
    def test_original_candidates_are_immutable_and_real_truth_validates(self):
        for ref, expected_hash in HASHES.items():
            path = ROOT / "stage5/pilot" / f"{ref}.json"
            before = path.read_bytes()
            self.assertEqual(hashlib.sha256(before).hexdigest(), expected_hash)
            truth = json.loads((ROOT / "stage5_1/truth" / f"{ref}.json").read_text())
            validate_truth(truth)
            result = compare(json.loads(before), truth)
            self.assertEqual(result["source_ref"], ref)
            self.assertEqual(path.read_bytes(), before)
        for name, expected_hash in SUPPORTING_HASHES.items():
            self.assertEqual(hashlib.sha256((ROOT / "stage5/pilot" / name).read_bytes()).hexdigest(),
                             expected_hash)

    def test_unsupported_ontology_and_structure_rejected(self):
        truth = json.loads((ROOT / "stage5_1/truth/01.json").read_text())
        bad = copy.deepcopy(truth)
        bad["items"][0]["technique_id"] = "hook.fabricated"
        with self.assertRaisesRegex(ValueError, "Unsupported ontology ID"):
            validate_truth(bad)
        bad = copy.deepcopy(truth)
        bad["structure"][0]["role"] = "viral_intro"
        with self.assertRaisesRegex(ValueError, "Unsupported structure role"):
            validate_truth(bad)

    def test_partial_truth_abstains_and_one_to_one_prevents_recall_inflation(self):
        guesses = [prediction(), prediction()]
        one = [reviewed()]
        self.assertEqual(len(one_to_one(guesses, one, lambda a, b: a["technique_id"] == b["technique_id"])), 1)
        scored = _score(guesses, one, {"cta": "complete"}, label_key="technique_id")
        self.assertEqual((scored["tp"], scored["fp"], scored["fn"]), (1, 1, 0))
        partial = _score([], [reviewed(coverage="partial")], {"cta": "partial"}, label_key="technique_id")
        self.assertEqual((partial["tp"], partial["fp"], partial["fn"]), (0, 0, 0))
        complete = _score([], one, {"cta": "complete"}, label_key="technique_id")
        self.assertEqual(complete["fn"], 1)

    def test_temporal_support_requires_relevant_substantive_evidence(self):
        content = {"metadata": {"duration_seconds": 10.0},
                   "transcript": [{"ref": "transcript:0", "start_seconds": 0.0,
                                   "end_seconds": 1.0, "text": "hello"}],
                   "ocr": [{"ref": "ocr:0", "start_seconds": 8.0, "end_seconds": 9.0,
                            "text": "later"},
                           {"ref": "ocr:1", "start_seconds": 5.5, "end_seconds": 6.5,
                            "text": "now"}],
                   "scenes": [{"ref": "scene:0", "start_seconds": 5.0,
                                            "end_seconds": 7.0}]}
        frames = [{"ref": "frame:0", "timestamp_seconds": 5.5}]
        catalog = evidence_catalog(content, frames)
        draft = SemanticDraft.model_validate({"findings": [{
            "technique_id": "visual.close_up", "start_seconds": 5.0,
            "end_seconds": 6.0, "confidence": 0.7, "basis": "direct_observation",
            "rationale": "Visible close framing",
            "evidence_refs": ["transcript:0", "ocr:0", "ocr:1", "frame:0"]}],
            "structure": [], "uncertainties": []})
        support = temporal_evidence_support(draft.findings[0], catalog)
        self.assertEqual(support["interval_support"], ["ocr:1", "frame:0"])
        self.assertEqual(support["context_support"], ["transcript:0", "ocr:0"])
        validate_draft(draft, content, frames)
        draft.findings[0].evidence_refs = ["transcript:0", "scene:0"]
        with self.assertRaisesRegex(ValueError, "temporally relevant interval support"):
            validate_draft(draft, content, frames)
        draft.findings[0].evidence_refs = ["transcript:0"]
        with self.assertRaisesRegex(ValueError, "temporally relevant interval support"):
            validate_draft(draft, content, frames)
        draft.findings[0].evidence_refs = ["frame:0"]
        draft.structure = [SemanticDraft.model_validate({"findings": [], "structure": [{
            "role": "demonstration", "start_seconds": 5.0, "end_seconds": 6.0,
            "confidence": 0.7, "rationale": "Demonstration interval",
            "evidence_refs": ["transcript:0", "scene:0"]}],
            "uncertainties": []}).structure[0]]
        with self.assertRaisesRegex(ValueError, "Structure lacks temporally relevant"):
            validate_draft(draft, content, frames)
        draft.structure[0].evidence_refs.append("frame:0")
        validate_draft(draft, content, frames)

    def test_duplicates_cta_overlap_and_structure_contradictions_are_flags(self):
        flags = _flags([prediction(), prediction(), prediction("cta.product")], [
            {"role": "setup", "start_seconds": 1, "end_seconds": 4},
            {"role": "payoff", "start_seconds": 1, "end_seconds": 4}])
        self.assertEqual(flags["duplicate_prediction_count"], 1)
        self.assertEqual(len(flags["cta_same_event_pairs"]), 3)
        self.assertEqual(flags["contradictory_prediction_count"], 1)

    def test_semantic_input_still_excludes_motion_and_performance(self):
        analysis = {"metadata": {"duration_seconds": 5, "video": {"fps": 30,
                    "resolution": {"width": 720, "height": 1280}}},
                    "audio": {"segments": []}, "on_screen_text": [], "scenes": [],
                    "motion_events": [{"type": "camera_zoom"}],
                    "performance_metrics": {"views": 500}, "previous_recommendations": ["zoom"]}
        serialized = json.dumps(semantic_input(analysis))
        for forbidden in ("motion_events", "camera_zoom", "performance_metrics", "views", "previous_recommendations"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
