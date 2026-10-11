"""Evidence-first inference boundaries and provenance gates."""

import hashlib
import json
import unittest
from pathlib import Path

from intelligence.evaluation.stage5_4_semantic import (
    ChunkDescription, SynthesisDraft, chunk_plan, cta_event_audit,
    pass1_content, pass2_content, validate_chunk, validate_synthesis,
)
from intelligence.evaluation.stage5_semantic import evidence_catalog, semantic_input
from intelligence.ontology import techniques

ROOT = Path(__file__).resolve().parents[1] / "intelligence/evaluation"
DIGESTS = {
    "stage5/pilot": "4daa6005c0c12645b9ce090aee69636693170beb0aea42bafee78b8371da0e20",
    "stage5_1/truth": "200ad176986d5207b3befb488b62d8a3a6429726a1a1d2105f8b1ef638230089",
    "stage5_1/comparisons": "d290c4eaf2f8e0e691988612539576870bb9154d29d2d7c356d2d160c26343fa",
    "stage5_2/candidates": "c52877f5c6e51f5700b36e13769fa0e0c42e14c55849c159855c1b3d2350a58a",
    "stage5_2/comparisons": "148aff92f641052425e18e3f88a510fe71411f40f2dd65ebb9fb424adbe3a9f9",
    "stage5_3/candidates": "565034ec8cbca17421861f6f686c4d25190d4fa484e483aa8b09a87176482b05",
    "stage5_3/comparisons": "679857a84b7355b823b2f7ac0a4e4748bc4cba75839c9f7c9e3ea28831b3eec9",
}


def observation(start, end, refs, *, objects=None, actions=None, text=None):
    return {"start_seconds": start, "end_seconds": end,
            "boundary_reason": "chunk_boundary",
            "visible_subjects_objects": objects or [], "visible_actions": actions or [],
            "visible_text": text or [], "spoken_content_summary": "Not established",
            "changes_from_previous_chunk": "Not established", "confidence": .8,
            "evidence_refs": refs, "uncertainties": []}


class Stage54Tests(unittest.TestCase):
    def setUp(self):
        raw = {"metadata": {"duration_seconds": 10.0, "video": {"fps": 30,
               "resolution": {"width": 720, "height": 1280}, "private_performance": 100}},
               "audio": {"segments": [{"start": 0, "end": 2, "text": "Please visit"}]},
               "on_screen_text": [{"appearance_timestamp_seconds": 8,
                                   "disappearance_timestamp_seconds": 10,
                                   "text": "Visit the site"}],
               "scenes": [{"start_seconds": 0, "end_seconds": 5},
                          {"start_seconds": 5, "end_seconds": 10}],
               "motion_events": [{"secret_motion": 1}],
               "performance_metrics": {"secret_performance": 2},
               "stage5_1_reviewed_truth": {"secret_truth": 3}}
        self.content = semantic_input(raw)
        self.frames = [{"ref": "frame:0", "timestamp_seconds": 1.0,
                        "selection_reason": "opening", "jpeg_sha256": "a" * 64,
                        "_jpeg": b"jpeg"},
                       {"ref": "frame:1", "timestamp_seconds": 9.0,
                        "selection_reason": "final", "jpeg_sha256": "b" * 64,
                        "_jpeg": b"jpeg"}]
        self.chunks = [{"chunk_id": "chunk:0", "start_seconds": 0.0,
                        "end_seconds": 5.0, "frame_refs": ["frame:0"]},
                       {"chunk_id": "chunk:1", "start_seconds": 5.0,
                        "end_seconds": 10.0, "frame_refs": ["frame:1"]}]
        self.ledger = [
            {"ledger_id": "ledger:0:0", "chunk_id": "chunk:0",
             **observation(0, 2, ["frame:0", "transcript:0"],
                           objects=["Person and product"], actions=["Person holds product"])},
            {"ledger_id": "ledger:1:0", "chunk_id": "chunk:1",
             **observation(8, 10, ["frame:1", "ocr:0"],
                           objects=["Product"], text=["Visit the site"])}]

    def draft(self):
        assessments = [{"technique_id": name,
                        "ontology_definition": definition.description,
                        "decision": "unsupported", "criterion_explanation": "No support",
                        "positive_ledger_refs": [], "counterevidence_limitations": "No evidence"}
                       for name, definition in techniques().items() if name.startswith("format.")]
        return {"format_assessments": assessments, "cta_events": [],
                "findings": [], "structure": [], "uncertainties": []}

    def test_pass1_receives_only_allowlisted_chunk_evidence_and_no_ontology(self):
        ChunkDescription.model_json_schema()
        SynthesisDraft.model_json_schema()
        parts = pass1_content(self.content, self.frames, self.chunks[0], None)
        payload = parts[0]["text"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(json.loads(payload)["frames"][0]["ref"], "frame:0")
        for forbidden in ("ontology", "technique_id", "secret_truth", "secret_motion",
                          "secret_performance", "stage5_1_reviewed_truth", "motion_events"):
            self.assertNotIn(forbidden, payload)

    def test_pass1_rejects_ontology_ids_and_unsupplied_references(self):
        catalog = evidence_catalog(self.content, self.frames)
        base = {"chunk_start_seconds": 0, "chunk_end_seconds": 5,
                "observations": [observation(1, 1, ["frame:0"], objects=["Person"])],
                "uncertainties": []}
        self.assertEqual(len(validate_chunk(ChunkDescription.model_validate(base),
                                            self.chunks[0], catalog)), 1)
        base["observations"][0].update(start_seconds=1.0, end_seconds=1.0)
        validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)
        base["observations"][0].update(start_seconds=1.0, end_seconds=1.0)
        base["observations"][0]["visible_text"] = ["format.before_after"]
        with self.assertRaisesRegex(ValueError, "ontology ID"):
            validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)
        base["observations"][0]["visible_text"] = []
        base["observations"][0]["evidence_refs"] = ["frame:999"]
        with self.assertRaisesRegex(ValueError, "not supplied"):
            validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)
        base["observations"][0]["evidence_refs"] = ["frame:1"]
        with self.assertRaisesRegex(ValueError, "outside chunk"):
            validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)

    def test_pass2_receives_complete_ledger_and_frozen_definitions_without_private_inputs(self):
        payload = json.loads(pass2_content(self.content, self.ledger, self.chunks)[0]["text"])
        self.assertEqual(len(payload["evidence_ledger"]), 2)
        self.assertEqual(payload["ontology_version"], "1.1.0")
        self.assertIn("other", payload["structure_roles"])
        self.assertTrue(any(row["id"] == "format.before_after" for row in payload["ontology"]))
        self.assertFalse(any(row["id"].startswith("audio.") for row in payload["ontology"]))
        for forbidden in ("secret_truth", "secret_motion", "secret_performance",
                          "stage5_1_reviewed_truth", "performance_metrics", "motion_events"):
            self.assertNotIn(forbidden, json.dumps(payload))

    def test_each_interval_must_overlap_ledger_and_trace_to_original(self):
        draft = self.draft()
        draft["structure"] = [{"role": "setup", "start_seconds": 8,
                               "end_seconds": 10, "confidence": .8,
                               "rationale": "Text is visible", "evidence_refs": ["ledger:0:0"]}]
        with self.assertRaisesRegex(ValueError, "overlapping ledger"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)
        draft["structure"][0]["evidence_refs"] = ["ledger:1:0"]
        flat, _ = validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                                     self.content, self.frames)
        self.assertIn("ocr:0", flat.structure[0].evidence_refs)
        broken = [*self.ledger]
        broken[1] = {**broken[1], "evidence_refs": ["frame:999"]}
        with self.assertRaisesRegex(ValueError, "original evidence"):
            validate_synthesis(SynthesisDraft.model_validate(draft), broken,
                               self.content, self.frames)

    def test_whole_video_format_can_cite_separated_chunks(self):
        draft = self.draft()
        for row in draft["format_assessments"]:
            if row["technique_id"] == "format.product_demo":
                row.update(decision="supported", criterion_explanation="Product shown in use",
                           positive_ledger_refs=["ledger:0:0", "ledger:1:0"])
        draft["findings"] = [{"technique_id": "format.product_demo",
                              "start_seconds": 0, "end_seconds": None,
                              "confidence": .7, "basis": "model_interpretation",
                              "rationale": "Product shown at both ends",
                              "evidence_refs": ["ledger:0:0", "ledger:1:0"],
                              "event_id": None}]
        flat, report = validate_synthesis(SynthesisDraft.model_validate(draft),
                                          self.ledger, self.content, self.frames)
        self.assertEqual(flat.findings[0].evidence_refs,
                         ["frame:0", "transcript:0", "frame:1", "ocr:0"])
        self.assertEqual(report.techniques[0].technique_id, "format.product_demo")
        draft["findings"] = []
        flat, _ = validate_synthesis(SynthesisDraft.model_validate(draft),
                                     self.ledger, self.content, self.frames)
        self.assertEqual(flat.findings[0].technique_id, "format.product_demo")
        SynthesisDraft.model_validate(draft).model_dump(mode="json")

    def test_localized_format_support_and_literal_definition(self):
        draft = self.draft()
        row = next(row for row in draft["format_assessments"]
                   if row["technique_id"] == "format.product_demo")
        row.update(decision="supported", positive_ledger_refs=["ledger:0:0"],
                   criterion_explanation="Product use is shown locally")
        flat, _ = validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                                     self.content, self.frames)
        self.assertEqual(flat.findings[0].technique_id, "format.product_demo")
        row["ontology_definition"] = "Must dominate the runtime"
        with self.assertRaisesRegex(ValueError, "frozen ontology"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)

    def test_atomic_boundary_reason_and_evidence_envelope(self):
        catalog = evidence_catalog(self.content, self.frames)
        item = observation(0, 2, ["frame:0", "transcript:0"])
        item["boundary_reason"] = "ocr_change"
        base = {"chunk_start_seconds": 0, "chunk_end_seconds": 5,
                "observations": [item], "uncertainties": []}
        with self.assertRaisesRegex(ValueError, "boundary reason"):
            validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)
        item["boundary_reason"] = "transcript_change"
        validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)
        item["end_seconds"] = 4
        normalized = validate_chunk(ChunkDescription.model_validate(base), self.chunks[0], catalog)[0]
        self.assertEqual(normalized["end_seconds"], 2)
        self.assertEqual(normalized["timing_adjustment"]["reason"],
                         "clamped_to_substantive_evidence_envelope")

    def test_primary_structure_overlap_rejected_but_gap_allowed(self):
        draft = self.draft()
        draft["structure"] = [
            {"role": "setup", "start_seconds": 0, "end_seconds": 2,
             "confidence": .8, "rationale": "Person and product", "evidence_refs": ["ledger:0:0"]},
            {"role": "cta", "start_seconds": 8, "end_seconds": 10,
             "confidence": .8, "rationale": "Visit site", "evidence_refs": ["ledger:1:0"]},
        ]
        validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                           self.content, self.frames)
        draft["structure"][1].update(start_seconds=1, end_seconds=2,
                                      evidence_refs=["ledger:0:0"])
        with self.assertRaisesRegex(ValueError, "incompatible primary roles"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)

    def test_synthesis_interval_cannot_extend_past_atomic_support(self):
        draft = self.draft()
        draft["structure"] = [{"role": "setup", "start_seconds": 0,
                               "end_seconds": 5, "confidence": .8,
                               "rationale": "Person and product",
                               "evidence_refs": ["ledger:0:0"]}]
        with self.assertRaisesRegex(ValueError, "broader than cited"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)

    def test_other_needs_visible_description(self):
        draft = self.draft()
        draft["structure"] = [{"role": "other", "start_seconds": 8,
                               "end_seconds": 10, "confidence": .6,
                               "rationale": "An unknown period exists here",
                               "evidence_refs": ["ledger:1:0"]}]
        with self.assertRaisesRegex(ValueError, "visible content"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)
        draft["structure"][0]["rationale"] = "Product and site text remain visible"
        validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                           self.content, self.frames)

    def test_point_only_interval_claims_are_omitted_from_frozen_report(self):
        draft = self.draft()
        draft["findings"] = [{"technique_id": "visual.product_foreground",
                              "start_seconds": 9, "end_seconds": 9, "confidence": .8,
                              "basis": "direct_observation", "rationale": "Product visible",
                              "evidence_refs": ["ledger:1:0"], "event_id": None}]
        draft["structure"] = [{"role": "demonstration", "start_seconds": 9,
                               "end_seconds": 9, "confidence": .8,
                               "rationale": "Product visible", "evidence_refs": ["ledger:1:0"]}]
        flat, report = validate_synthesis(SynthesisDraft.model_validate(draft),
                                          self.ledger, self.content, self.frames)
        self.assertEqual(flat.findings, [])
        self.assertEqual(report.structure, [])

    def test_cta_event_id_groups_labels_for_one_request(self):
        draft = self.draft()
        draft["cta_events"] = [{"event_id": "event:1", "start_seconds": 8,
                                "end_seconds": 10, "requested_action": "Visit the site",
                                "ledger_refs": ["ledger:1:0"]}]
        for name in ("cta.visual", "cta.product"):
            draft["findings"].append({"technique_id": name, "start_seconds": 8,
                "end_seconds": 10, "confidence": .8, "basis": "model_interpretation",
                "rationale": "Visit the site text", "evidence_refs": ["ledger:1:0"],
                "event_id": "event:1"})
        parsed = SynthesisDraft.model_validate(draft)
        validate_synthesis(parsed, self.ledger, self.content, self.frames)
        audit = cta_event_audit(parsed)
        self.assertEqual(audit["cta_event_count"], 1)
        self.assertEqual(audit["overlapping_cta_labels_same_event"], [[0, 1]])
        self.assertEqual(audit["overlapping_cta_labels_different_events"], [])
        draft["findings"][1]["event_id"] = "event:2"
        with self.assertRaisesRegex(ValueError, "unknown event"):
            validate_synthesis(SynthesisDraft.model_validate(draft), self.ledger,
                               self.content, self.frames)

    def test_chunking_is_deterministic_and_sized_from_runtime_and_frames(self):
        frames = [{"ref": f"frame:{i}", "timestamp_seconds": i * 5 + 1}
                  for i in range(12)]
        plan = chunk_plan(60, frames, [])
        self.assertEqual(plan, chunk_plan(60, frames, []))
        self.assertEqual(len(plan), 3)
        self.assertLessEqual(max(len(row["frame_refs"]) for row in plan), 6)

    def test_previous_artifacts_are_unchanged(self):
        for directory, expected in DIGESTS.items():
            digest = hashlib.sha256()
            for path in sorted((ROOT / directory).iterdir()):
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
            self.assertEqual(digest.hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
