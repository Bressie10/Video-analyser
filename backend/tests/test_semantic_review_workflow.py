"""Blind package, reviewer contract, immutable adjudication, and gated scoring."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.semantic_review_workflow import (
    AnnotationContent, ReviewerRecord, blank_reviewer_template, compare_candidate,
    compare_reviewers, finalize_adjudication, load_reference, make_blind_package,
    prepare_adjudication, render_blind_guide,
)
from intelligence.ontology import techniques

PACKAGE = Path(__file__).resolve().parents[1] / "intelligence/evaluation/semantic_review_package/blind"


def annotation(identifier, start=None, end=None, *, status="present"):
    return {"technique_id": identifier, "status": status, "confidence": .8,
            "evidence_note": "Observed in the source video", "start_seconds": start,
            "end_seconds": end}


def review(reviewer_id="reviewer-a"):
    return {"review_version": "v9-independent-review-1", "ontology_version": "1.1.0",
            "source_ref": "01", "duration_seconds": 10.0,
            "provenance": {"reviewer_id": reviewer_id, "reviewer_type": "human",
                           "full_video_watched": True, "audio_heard": True,
                           "blind": True, "seen_contentmetric_outputs_previously": False,
                           "reviewed_at": "2026-10-12T12:00:00+00:00"},
            "category_coverage": {key: "complete" for key in
                                  ("hook", "format", "editing", "text", "audio", "cta", "visual")},
            "structure_coverage": "complete",
            "items": [annotation("hook.question", 0, 2),
                      annotation("format.product_demo"),
                      annotation("audio.music", 0, 10)],
            "cta_events": [{"event_id": "event-1", "status": "present", "confidence": .9,
                            "evidence_note": "Visible request card", "requested_action": "Visit a store",
                            "start_seconds": 8, "end_seconds": 10,
                            "labels": [annotation("cta.visual", 8, 10),
                                       annotation("cta.product", 8, 10)]}],
            "structure": [{"role": "hook", "status": "present", "confidence": .8,
                           "evidence_note": "Opening question", "start_seconds": 0,
                           "end_seconds": 2},
                          {"role": "cta", "status": "present", "confidence": .9,
                           "evidence_note": "Closing request", "start_seconds": 8,
                           "end_seconds": 10}]}


class SemanticReviewWorkflowTests(unittest.TestCase):
    def test_blind_package_has_exact_frozen_definitions_and_no_review_leakage(self):
        guide = render_blind_guide()
        self.assertEqual(guide, (PACKAGE / "REVIEWER_GUIDE.md").read_text())
        example = json.loads(guide.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(example["cta_events"][0]["labels"][0]["technique_id"], "cta.visual")
        for item in techniques().values():
            self.assertIn(f"`{item.id}` | {item.observation_kind} | {item.description}", guide)
        for forbidden in ("Stage 5", "Stage 5.1", "Stage 5.4", "provisional truth",
                          "prediction", "score", "confidence 0.8", "01: ", "04: "):
            # Generic instructions may mention predictions or scores only as things not to view.
            if forbidden in ("prediction", "score"):
                continue
            self.assertNotIn(forbidden, guide)
        expected = {"REVIEWER_GUIDE.md", *(f"templates/{source}.json" for source in
                                               ("01", "04", "08", "12"))}
        self.assertEqual({str(path.relative_to(PACKAGE)) for path in PACKAGE.rglob("*")
                          if path.is_file()}, expected)
        for source in ("01", "04", "08", "12"):
            template = json.loads((PACKAGE / "templates" / f"{source}.json").read_text())
            self.assertEqual(template, blank_reviewer_template(source))
            self.assertEqual(template["items"], [])
            self.assertEqual(template["cta_events"], [])
        with tempfile.TemporaryDirectory() as directory:
            make_blind_package(Path(directory))
            self.assertEqual((Path(directory) / "REVIEWER_GUIDE.md").read_text(), guide)

    def test_valid_ids_and_timing_pass_unsupported_ids_and_overlap_fail(self):
        ReviewerRecord.model_validate(review())
        invalid = review()
        invalid["items"][0]["technique_id"] = "hook.not_frozen"
        with self.assertRaisesRegex(ValueError, "Unsupported ontology ID"):
            ReviewerRecord.model_validate(invalid)
        invalid = review()
        invalid["structure"].append({"role": "explanation", "status": "present",
                                     "confidence": .8, "evidence_note": "Overlap",
                                     "start_seconds": 1, "end_seconds": 3})
        with self.assertRaisesRegex(ValueError, "Incompatible primary"):
            ReviewerRecord.model_validate(invalid)
        invalid = review()
        invalid["items"][1]["start_seconds"] = 1
        with self.assertRaisesRegex(ValueError, "Whole-video"):
            ReviewerRecord.model_validate(invalid)

    def test_disagreements_and_final_reference_preserve_original_reviewers(self):
        first = review()
        second = review("reviewer-b")
        second["items"] = [annotation("hook.question", 0, 2.5),
                           annotation("format.product_demo", status="absent"),
                           annotation("audio.music", 0, 10)]
        second["cta_events"] = [
            {**copy.deepcopy(first["cta_events"][0]), "event_id": "part-1",
             "end_seconds": 9, "labels": [annotation("cta.visual", 8, 9)]},
            {**copy.deepcopy(first["cta_events"][0]), "event_id": "part-2",
             "start_seconds": 9, "labels": [annotation("cta.product", 9, 10)]}]
        second["structure"][0]["role"] = "setup"
        disagreement = compare_reviewers(ReviewerRecord.model_validate(first),
                                         ReviewerRecord.model_validate(second))
        self.assertTrue(disagreement["whole_video_format_disagreements"])
        self.assertTrue(disagreement["interval_boundary_disagreements"])
        self.assertTrue(disagreement["cta_event_grouping_and_labels"]["grouping_disagreement"])
        self.assertTrue(disagreement["primary_structure_disagreements"]["paired_intervals"][0][
            "role_disagreement"])
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            paths = [folder / "a.json", folder / "b.json"]
            for path, value in zip(paths, (first, second)):
                path.write_text(json.dumps(value) + "\n")
            before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
            template = folder / "adjudication.json"
            pending = prepare_adjudication(paths, template)
            self.assertEqual(pending["review_count"], 2)
            self.assertEqual(pending["human_reviewer_count"], 2)
            self.assertIsNone(pending["resolved_annotation"])
            with self.assertRaisesRegex(ValueError, "adjudicated reference"):
                load_reference(template)
            pending["adjudicator"] = {"adjudicator_id": "adjudicator-x",
                                      "reviewer_type": "human", "full_video_watched": True,
                                      "audio_heard": True,
                                      "adjudicated_at": "2026-10-13T12:00:00+00:00"}
            pending["resolution_notes"] = ["Reviewed both original records and the full video."]
            pending["resolved_annotation"] = {key: value for key, value in first.items()
                                               if key not in ("review_version", "ontology_version",
                                                              "provenance")}
            template.write_text(json.dumps(pending) + "\n")
            reference_path = folder / "reference.json"
            finalized = finalize_adjudication(template, paths, reference_path)
            self.assertEqual(finalized["reference_status"], "adjudicated")
            self.assertFalse(finalized["gold_truth"])
            self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths], before)
            self.assertTrue(reference_path.exists())
            with self.assertRaisesRegex(ValueError, "separate file"):
                finalize_adjudication(template, paths, paths[0])
            paths[0].write_text(paths[0].read_text() + " ")
            with self.assertRaisesRegex(ValueError, "hashes changed"):
                finalize_adjudication(template, paths, folder / "another.json")

    def test_one_reviewer_limit_and_partial_coverage_abstain(self):
        raw = review()
        raw["category_coverage"]["audio"] = "partial"
        raw["items"] = [item for item in raw["items"] if item["technique_id"] != "audio.music"]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "one.json"
            path.write_text(json.dumps(raw) + "\n")
            prepared = prepare_adjudication([path], folder / "pending.json")
            self.assertEqual(prepared["review_count"], 1)
            self.assertTrue(prepared["single_reviewer_limit"])
            self.assertTrue(prepared["fewer_than_two_human_reviewers"])
            self.assertEqual(prepared["pairwise_disagreements"], [])
            other = copy.deepcopy(raw)
            other["provenance"]["reviewer_id"] = "other-reviewer"
            other["provenance"]["reviewer_type"] = "other"
            other_path = folder / "other.json"
            other_path.write_text(json.dumps(other) + "\n")
            mixed = prepare_adjudication([path, other_path], folder / "mixed.json")
            self.assertEqual(mixed["review_count"], 2)
            self.assertEqual(mixed["human_reviewer_count"], 1)
            self.assertTrue(mixed["fewer_than_two_human_reviewers"])
        content = AnnotationContent.model_validate({key: value for key, value in raw.items()
                                                    if key not in ("review_version", "ontology_version",
                                                                   "provenance")})
        candidate = {"source_ref": "01", "semantic_draft": {
            "findings": [{"technique_id": "hook.question", "start_seconds": 0,
                          "end_seconds": 2},
                         {"technique_id": "format.product_demo", "start_seconds": 0,
                          "end_seconds": None},
                         {"technique_id": "audio.music", "start_seconds": 0,
                          "end_seconds": 10}],
            "structure": [{"role": "hook", "start_seconds": 0, "end_seconds": 2},
                          {"role": "cta", "start_seconds": 8, "end_seconds": 10}]},
            "synthesis_draft": {"findings": [], "structure": []}, "cta_events": []}
        reference = {"reference_version": "v9-semantic-adjudicated-reference-1",
                     "reference_status": "limited_human_review_adjudicated", "review_count": 1,
                     "human_reviewer_count": 1,
                     "annotation": content.model_dump(mode="json")}
        result = compare_candidate(candidate, reference)
        self.assertEqual(result["reference_review_count"], 1)
        self.assertEqual(result["reference_human_reviewer_count"], 1)
        self.assertEqual(result["label"]["scored_prediction_count"], 2)
        self.assertEqual(result["label"]["tp"], 2)
        self.assertIn("0.25", result["interval_matching"])
        self.assertIsNotNone(result["structure_role_agreement"])

    def test_nonblind_and_incomplete_viewing_cannot_enter_adjudication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            raw = review()
            raw["provenance"]["blind"] = False
            path.write_text(json.dumps(raw) + "\n")
            with self.assertRaisesRegex(ValueError, "must be blind"):
                prepare_adjudication([path], Path(directory) / "pending.json")
            raw["provenance"]["blind"] = True
            raw["provenance"]["audio_heard"] = False
            raw["category_coverage"]["audio"] = "unavailable"
            raw["items"] = [item for item in raw["items"]
                            if item["technique_id"] != "audio.music"]
            path.write_text(json.dumps(raw) + "\n")
            with self.assertRaisesRegex(ValueError, "complete video with audio"):
                prepare_adjudication([path], Path(directory) / "pending.json")


if __name__ == "__main__":
    unittest.main()
