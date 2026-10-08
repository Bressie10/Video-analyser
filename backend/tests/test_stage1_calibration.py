"""Synthetic-only checks for the private Stage 1 workflow."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.stage1 import (
    annotation_audit, evaluate_one, evaluate_pilot, load_manifest, run,
)


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
    return {"source_ref": ref, "coverage": {signal: "complete" for signal in
            ("scene_boundaries", "ocr", "transcript", "motion", "metadata")},
            "scene_boundaries": [{"time_seconds": 2.0, "note": "editorial boundary"}],
            "ocr": [{"text": "Video Test", "normalized_text": "video test",
                     "start_seconds": 0.5, "end_seconds": 4.0, "note": "visible title"}],
            "transcript": {"text": "hello world", "segments": [
                {"text": "hello world", "start": 0.2, "end": 1.2}]},
            "motion": [{"type": "local_motion", "start_seconds": 0.5,
                        "end_seconds": 1.5, "note": "moving hand"}],
            "metadata": {"duration_seconds": {"value": 4.0, "tolerance": 0.05},
                         "video.resolution.width": {"value": 640, "tolerance": 0},
                         "video.fps": {"value": 30, "tolerance": 0.1}}}


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
        self.assertEqual(result["ocr"]["result"]["missed_visible_text_rate"], 1)
        self.assertEqual(result["transcript"]["result"]["missing_speech_segments"], 1)
        self.assertEqual(result["transcript"]["result"]["hallucinated_speech_segments"], 1)
        self.assertEqual(result["motion"]["result"]["type_confusion"][0]["predicted"], "camera_pan")
        truth["coverage"]["ocr"] = "partial"
        self.assertEqual(evaluate_one(analysis, truth)["ocr"],
                         {"status": "abstained", "reason": "partial"})
        truth["coverage"]["ocr"] = "complete"
        truth["ocr"] = []
        self.assertIsNone(evaluate_one(analysis, truth)["ocr"]["result"]["missed_visible_text_rate"])
        del truth["ocr"]
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate_one(analysis, truth)

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
            truth_dir = root / "truth"
            truth_dir.mkdir()
            for i in range(9):
                (truth_dir / f"synthetic-{i}.json").write_text(json.dumps(synthetic_truth(f"synthetic-{i}")))
            report = evaluate_pilot(path, output, truth_dir)
            self.assertEqual(report["sources"]["synthetic-9"]["status"], "missing_data")
            self.assertEqual(report["coverage"]["scene_boundaries"]["measured"], 9)
            self.assertEqual(report, evaluate_pilot(path, output, truth_dir))
            custom = evaluate_pilot(path, output, truth_dir, scene_tolerances=(0.2,))
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
