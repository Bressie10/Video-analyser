"""Synthetic-only checks for the private Stage 1 workflow."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.stage1 import (
    annotation_audit, evaluate_one, evaluate_pilot, load_manifest, low_level_audit, run,
)
from intelligence.evaluation.stage1_truth import compare_records, validate_record


FIXTURES = Path(__file__).resolve().parents[1] / "intelligence/evaluation/fixtures"
EXAMPLES = Path(__file__).resolve().parents[1] / "intelligence/evaluation/examples"


def synthetic_manifest(root):
    return {"schema_version": 1, "sources": [
        {"source_ref": f"synthetic-{i}", "media_path": str(root / f"media-{i}.mp4"),
         "duration_seconds": 4.0, "creator_ref": f"creator-{i}",
         "rights_note": "generated test data", "annotation_status": "pending",
         "partition": "test", "group_ref": f"group-{i}",
         "low_level_truth_available": True, "variation": ["talking_head", "ordinary"]}
        for i in range(10)]}


def synthetic_truth(ref="synthetic-0"):
    return {"low_level_truth_version": "1.0.0", "source_ref": ref,
            "record_kind": "reviewed", "reviewer_ref": "reviewer",
            "reviewed_at": "2026-10-08T12:00:00Z", "notes": None,
            "coverage": {signal: "complete" for signal in
            ("scene_boundaries", "ocr", "transcript", "motion", "metadata")},
            "observations": {
            "scene_boundaries": [{"time_seconds": 2.0, "note": "editorial boundary"}],
            "ocr": [{"text": "Video Test", "normalized_text": "video test",
                     "start_seconds": 0.5, "end_seconds": 4.0, "note": "visible title"}],
            "transcript": {"text": "hello world", "segments": [
                {"text": "hello world", "start": 0.2, "end": 1.2}]},
            "motion": [{"type": "local_motion", "start_seconds": 0.5,
                        "end_seconds": 1.5, "note": "moving hand"}],
            "metadata": {"duration_seconds": {"value": 4.0, "tolerance": 0.05},
                         "video.resolution.width": {"value": 640, "tolerance": 0},
                         "video.fps": {"value": 30, "tolerance": 0.1}}}}


def independent(truth, annotator):
    record = copy.deepcopy(truth)
    record["record_kind"] = "independent"
    record["annotator_ref"] = annotator
    record["annotated_at"] = record.pop("reviewed_at")
    record.pop("reviewer_ref")
    return record


def write_review_set(root, truth):
    ref = truth["source_ref"]
    annotations = root / "annotations"
    reviewed = root / "reviewed"
    annotations.mkdir(parents=True, exist_ok=True)
    reviewed.mkdir(parents=True, exist_ok=True)
    for name in ("a", "b"):
        (annotations / f"{ref}__{name}.json").write_text(json.dumps(independent(truth, name)))
    (reviewed / f"{ref}.json").write_text(json.dumps(truth))
    (reviewed / f"{ref}.md").write_text(f"{ref}: reviewed both independent records against media.\n")


def low_level_fixture(root):
    manifest = synthetic_manifest(root)
    for item in manifest["sources"][1:]:
        item["low_level_truth_available"] = False
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    low_level = root / "low_level"
    truth = synthetic_truth()
    write_review_set(low_level, truth)
    return path, low_level, truth


def synthetic_analysis():
    value = json.loads((FIXTURES / "synthetic_analysis.json").read_text())
    value["metadata"]["video"]["fps"] = 30
    value["audio"] = {"text": "hello world", "segments": [
        {"text": "hello world", "start": 0.3, "end": 1.3}]}
    return value


class Stage1Tests(unittest.TestCase):
    def test_manifest_validation_and_grouping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            manifest = synthetic_manifest(root)
            path.write_text(json.dumps(manifest))
            self.assertEqual(len(load_manifest(path)["sources"]), 10)
            manifest["sources"][1]["group_ref"] = "group-0"
            manifest["sources"][1]["partition"] = "train"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "cannot cross"):
                load_manifest(path)
            manifest["sources"][1]["group_ref"] = "group-1"
            manifest["sources"][1]["source_ref"] = "../escape"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "safe identifiers"):
                load_manifest(path)
            manifest["sources"][1]["source_ref"] = "synthetic-1"
            manifest["sources"][1]["creator_ref"] = "creator-0"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "one source group"):
                load_manifest(path)

    def test_all_signal_comparisons_and_determinism(self):
        analysis, truth = synthetic_analysis(), synthetic_truth()
        result = evaluate_one(analysis, truth)
        self.assertEqual(result, evaluate_one(analysis, truth))
        self.assertEqual(result["scene_boundaries"]["result"]["0.1"]["f1"], 1.0)
        self.assertEqual(result["ocr"]["result"]["exact_text"]["recall"], 1.0)
        self.assertAlmostEqual(result["transcript"]["result"]["segment_timing_mean_error_seconds"], 0.1)
        self.assertEqual(result["motion"]["result"]["presence_overlap"]["tp"], 1)
        self.assertTrue(result["metadata"]["result"]["video.fps"]["correct"])

    def test_misses_confusion_empty_and_partial_coverage(self):
        analysis, truth = synthetic_analysis(), synthetic_truth()
        analysis["scenes"].append({"cut_timestamp_seconds": 3.0})
        analysis["on_screen_text"] = []
        analysis["audio"] = {"text": "invented words", "segments": [
            {"text": "invented words", "start": 2.0, "end": 3.0}]}
        analysis["motion_events"][0]["type"] = "camera_pan"
        result = evaluate_one(analysis, truth)
        self.assertEqual(result["scene_boundaries"]["result"]["0.25"]["fp"], 1)
        self.assertEqual(result["ocr"]["result"]["unmatched_visible_text_span_rate"], 1)
        self.assertEqual(result["transcript"]["result"]["missing_speech_segments"], 1)
        self.assertEqual(result["transcript"]["result"]["hallucinated_speech_segments"], 1)
        self.assertEqual(result["motion"]["result"]["type_confusion"][0]["predicted"], "camera_pan")
        truth["coverage"]["ocr"] = "partial"
        self.assertEqual(evaluate_one(analysis, truth)["ocr"],
                         {"status": "abstained", "reason": "partial"})
        truth["coverage"]["ocr"] = "complete"
        truth["observations"]["ocr"] = []
        self.assertIsNone(evaluate_one(analysis, truth)["ocr"]["result"]["unmatched_visible_text_span_rate"])
        del truth["observations"]["ocr"]
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate_one(analysis, truth)

    def test_ocr_temporal_pair_can_have_wrong_text(self):
        analysis, truth = synthetic_analysis(), synthetic_truth()
        analysis["on_screen_text"][0]["text"] = "wrong words"
        result = evaluate_one(analysis, truth)["ocr"]["result"]
        self.assertEqual(result["unmatched_visible_text_span_rate"], 0)
        self.assertEqual(result["exact_text"]["recall"], 0)

    def test_low_level_audit_requires_two_distinct_passes_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, root, truth = low_level_fixture(Path(tmp))
            # The human-truth audit does not read any pipeline result file.
            self.assertEqual(low_level_audit(path, root)["reviewed_sources"], ["synthetic-0"])
            cli = subprocess.run([sys.executable, "-m", "intelligence.evaluation.stage1",
                                  "low-level-audit", str(path), "--low-level", str(root)],
                                 capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(json.loads(cli.stdout)["reviewed_sources"], ["synthetic-0"])
            second = root / "annotations/synthetic-0__b.json"
            original = second.read_text()
            second.unlink()
            with self.assertRaisesRegex(ValueError, "Two independent"):
                low_level_audit(path, root)
            second.write_text(original)
            duplicate = independent(truth, "a")
            second.write_text(json.dumps(duplicate))
            with self.assertRaisesRegex(ValueError, "Same low-level annotator"):
                low_level_audit(path, root)
            duplicate["annotator_ref"] = "b"
            duplicate["low_level_truth_version"] = "2.0.0"
            second.write_text(json.dumps(duplicate))
            with self.assertRaisesRegex(ValueError, "version"):
                low_level_audit(path, root)

    def test_low_level_audit_requires_notes_and_reviewer_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, root, truth = low_level_fixture(Path(tmp))
            notes = root / "reviewed/synthetic-0.md"
            notes.unlink()
            with self.assertRaisesRegex(ValueError, "adjudication notes"):
                low_level_audit(path, root)
            notes.write_text("Reviewed both records against media.\n")
            reviewed = root / "reviewed/synthetic-0.json"
            truth.pop("reviewer_ref")
            reviewed.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "reviewer_ref"):
                low_level_audit(path, root)
            truth["reviewer_ref"] = "a"
            reviewed.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "separate reviewer"):
                low_level_audit(path, root)
            truth["reviewer_ref"] = "reviewer"
            truth["reviewed_at"] = "2026-10-08T12:00:00"
            reviewed.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                low_level_audit(path, root)
            truth["reviewed_at"] = "2026-10-08T12:00:00Z"
            truth["reviewed_at"] = "2026-10-08T11:59:59Z"
            reviewed.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "predates"):
                low_level_audit(path, root)
            truth["reviewed_at"] = "2026-10-08T12:00:00Z"
            truth["analysis"] = synthetic_analysis()
            reviewed.write_text(json.dumps(truth))
            with self.assertRaisesRegex(ValueError, "detector output"):
                low_level_audit(path, root)

    def test_low_level_agreement_is_signal_specific_and_skips_incomplete_scope(self):
        first = independent(synthetic_truth(), "a")
        second = independent(synthetic_truth(), "b")
        second["observations"]["scene_boundaries"] = [{"time_seconds": 2.2}]
        second["observations"]["ocr"][0]["normalized_text"] = "different text"
        second["observations"]["transcript"]["text"] = "hello again"
        second["observations"]["transcript"]["segments"][0]["start"] = 0.3
        second["observations"]["motion"][0]["type"] = "camera_pan"
        second["observations"]["metadata"]["video.fps"]["value"] = 24
        report = compare_records(first, second, scene_tolerance=0.25)["signals"]
        self.assertAlmostEqual(report["scene_boundaries"]["result"]["matched"][0]["absolute_timing_difference_seconds"], 0.2)
        self.assertFalse(report["ocr"]["result"]["matched"][0]["normalized_text_agrees"])
        self.assertEqual(report["transcript"]["result"]["token_edit_distance"], 1)
        self.assertAlmostEqual(report["transcript"]["result"]["segment_timing"]["matched"][0]["start_difference_seconds"], 0.1)
        self.assertFalse(report["motion"]["result"]["matched"][0]["type_agrees"])
        self.assertFalse(report["metadata"]["result"]["video.fps"]["within_declared_tolerance"])
        second["coverage"]["ocr"] = "partial"
        first["coverage"]["motion"] = "unavailable"
        limited = compare_records(first, second)["signals"]
        self.assertEqual(limited["ocr"], {"status": "not_compared", "coverage": ["complete", "partial"]})
        self.assertEqual(limited["motion"], {"status": "not_compared", "coverage": ["unavailable", "complete"]})

    def test_evaluator_uses_reviewed_truth_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, low_level, truth = low_level_fixture(root)
            # Both independent passes say 2.0; reviewed truth says 3.0.
            truth["observations"]["scene_boundaries"] = [{"time_seconds": 3.0}]
            (low_level / "reviewed/synthetic-0.json").write_text(json.dumps(truth))
            results = root / "results"
            results.mkdir()
            payload = {"source_ref": "synthetic-0", "pipeline_version": "synthetic-v8",
                       "input_sha256": "synthetic-hash", "analysis": synthetic_analysis()}
            (results / "synthetic-0.json").write_text(json.dumps(payload))
            report = evaluate_pilot(path, results, low_level)
            scene = report["sources"]["synthetic-0"]["signals"]["scene_boundaries"]["result"]["0.25"]
            self.assertEqual((scene["tp"], scene["fp"], scene["fn"]), (0, 1, 1))
            (low_level / "reviewed/synthetic-0.json").unlink()
            with self.assertRaisesRegex(ValueError, "Reviewed low-level truth missing"):
                evaluate_pilot(path, results, low_level)

    def test_runner_result_loading_and_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = synthetic_manifest(root)
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            for i in range(10):
                (root / f"media-{i}.mp4").write_bytes(f"synthetic media {i}".encode())
            output = root / "results"
            run(path, output, analyzer=lambda _source, _work, allow_silent: synthetic_analysis())
            self.assertEqual(len(list(output.glob("*.json"))), 10)
            with self.assertRaises(FileExistsError):
                run(path, output, analyzer=lambda _source, _work, allow_silent: synthetic_analysis())
            low_level_dir = root / "low_level"
            for i in range(9):
                write_review_set(low_level_dir, synthetic_truth(f"synthetic-{i}"))
            manifest["sources"][9]["low_level_truth_available"] = False
            path.write_text(json.dumps(manifest))
            report = evaluate_pilot(path, output, low_level_dir)
            self.assertEqual(report["sources"]["synthetic-9"]["status"], "missing_data")
            self.assertEqual(report["coverage"]["scene_boundaries"]["measured"], 9)
            self.assertEqual(report, evaluate_pilot(path, output, low_level_dir))
            custom = evaluate_pilot(path, output, low_level_dir, scene_tolerances=(0.2,))
            self.assertEqual(list(custom["aggregate"]["scene_boundaries"]), ["0.2"])

    def test_annotation_audit_preserves_independent_and_reviewed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = synthetic_manifest(root)
            for item in manifest["sources"]:
                item["annotation_status"] = "reviewed"
            manifest_path = root / "pilot.json"
            manifest_path.write_text(json.dumps(manifest))
            semantic = root / "semantic"
            (semantic / "annotations").mkdir(parents=True)
            reviewed = root / "reviewed"
            reviewed.mkdir()
            example = json.loads((EXAMPLES / "annotations/clip-1__a.json").read_text())
            splits = []
            sources = []
            for i in range(10):
                ref = f"synthetic-{i}"
                sources.append({"reference_id": ref, "media_ref": str(root / f"media-{i}.mp4"), "notes": "synthetic"})
                splits.append({"source_ref": ref, "partition": "test", "group_ref": f"group-{i}"})
                for annotator in ("a", "b"):
                    record = copy.deepcopy(example)
                    record["annotation_ref"] = f"{ref}-{annotator}"
                    record["annotator_ref"] = annotator
                    record["source"]["reference_id"] = ref
                    record["source"]["duration_seconds"] = 4.0
                    record["structure"] = []
                    record["coverage"]["structure_complete"] = False
                    record["techniques"] = []
                    record["numeric_ground_truth"] = []
                    record["coverage"]["numeric_fields"] = []
                    (semantic / "annotations" / f"{ref}-{annotator}.json").write_text(json.dumps(record))
                record["annotation_ref"] = f"{ref}-reviewed"
                record["annotator_ref"] = "reviewer"
                (reviewed / f"{ref}.json").write_text(json.dumps(record))
                (reviewed / f"{ref}.md").write_text("Both agree; no disputed label.\n")
            (semantic / "manifest.json").write_text(json.dumps({"sources": sources, "split_assignments": splits}))
            report = annotation_audit(manifest_path, semantic, reviewed)
            self.assertEqual(len(report["agreement"]), 10)
            (reviewed / "synthetic-0.md").unlink()
            with self.assertRaisesRegex(ValueError, "adjudication notes"):
                annotation_audit(manifest_path, semantic, reviewed)


if __name__ == "__main__":
    unittest.main()
