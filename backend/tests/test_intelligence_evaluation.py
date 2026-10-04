"""Synthetic, offline tests for annotation dataset tooling."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.agreement import compare, compare_all, interval_iou, point_distances
from intelligence.evaluation.dataset import load_dataset, summarize
from intelligence.schemas.annotation import Annotation


EXAMPLE = Path(__file__).resolve().parents[1] / "intelligence/evaluation/examples"


def fixture():
    return (json.loads((EXAMPLE / "manifest.json").read_text()),
            [json.loads(path.read_text()) for path in sorted((EXAMPLE / "annotations").glob("*.json"))])


def write_dataset(root, manifest, annotations):
    (root / "annotations").mkdir()
    (root / "manifest.json").write_text(json.dumps(manifest))
    for index, annotation in enumerate(annotations):
        (root / "annotations" / f"{index}.json").write_text(json.dumps(annotation))


class EvaluationTests(unittest.TestCase):
    def test_example_validation_summary_and_cli(self):
        dataset, _ = load_dataset(EXAMPLE)
        summary = summarize(dataset)
        self.assertEqual(summary["annotations"], 2)
        self.assertEqual(summary["sources"], 1)
        self.assertEqual(summary["label_frequencies"]["hook.question"], 2)
        self.assertEqual(summary["coverage_counts"]["hook"], 2)
        self.assertEqual(summary["coverage_counts"]["audio"], 0)
        self.assertEqual(summary["coverage_counts"]["structure"], 0)
        self.assertEqual(summary["coverage_counts"]["structure_roles"], 2)
        self.assertEqual(summary["annotator_overlap"]["synthetic-clip-1"], ["example-a", "example-b"])
        self.assertIn("audio", summary["missing_categories"]["synthetic-clip-1-a"])
        for command in ("validate", "summary", "agreement"):
            result = subprocess.run([sys.executable, "-m", "intelligence.evaluation", command,
                                     str(EXAMPLE)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)

    def test_incomplete_scope_excluded_from_agreement(self):
        _, records = fixture()
        records[1]["coverage"]["complete_technique_categories"] = ["format"]
        records[1]["coverage"]["structure_complete"] = False
        result = compare(Annotation.model_validate_json(json.dumps(records[0])),
                         Annotation.model_validate_json(json.dumps(records[1])))
        self.assertNotIn("hook.question", result["label_presence"])
        self.assertIsNone(result["structure_role_iou"])
        self.assertEqual(result["complete_categories_compared"], ["format"])

    def test_three_annotators_produce_three_pairs(self):
        dataset, _ = load_dataset(EXAMPLE)
        third = dataset.annotations[0].model_copy(update={"annotation_ref": "synthetic-clip-1-c",
                                                      "annotator_ref": "example-c"})
        self.assertEqual(len(compare_all([*dataset.annotations, third])), 3)

    def test_interval_union_and_empty(self):
        self.assertEqual(interval_iou([(0, 2), (1, 3)], [(2, 4)]), 0.25)
        self.assertIsNone(interval_iou([], []))
        self.assertEqual(interval_iou([(0, 1)], []), 0.0)

    def test_point_timing_and_structure(self):
        dataset, _ = load_dataset(EXAMPLE)
        result = compare_all(dataset.annotations)[0]
        self.assertEqual(result["label_presence"]["editing.jump_cut"]["point_timing"],
                         {"distances_seconds": [0.2], "unmatched": 0})
        self.assertAlmostEqual(result["structure_role_iou"]["hook"], 1.7 / 1.8, places=4)
        self.assertEqual(result["structure_role_iou"]["payoff"], 1.0)
        self.assertEqual(point_distances([1, 3], [1.1, 2.0, 3.2])["unmatched"], 1)

    def test_duplicate_sources_and_split_leakage(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = copy.deepcopy(manifest)
            duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
            write_dataset(root, duplicate, records)
            with self.assertRaisesRegex(ValueError, "Duplicate source"):
                load_dataset(root)
            duplicate["sources"].pop()
            duplicate["sources"].append({"reference_id": "synthetic-clip-2",
                                         "media_ref": "synthetic://clip-1", "notes": "Duplicate media"})
            (root / "manifest.json").write_text(json.dumps(duplicate))
            with self.assertRaisesRegex(ValueError, "Duplicate media"):
                load_dataset(root)
            duplicate["sources"].pop()
            third = copy.deepcopy(records[0])
            third["annotation_ref"] = "synthetic-clip-2-a"
            third["source"]["reference_id"] = "synthetic-clip-2"
            duplicate["sources"].append({"reference_id": "synthetic-clip-2",
                                         "media_ref": "synthetic://clip-2", "notes": "Invented"})
            duplicate["split_assignments"].append({"source_ref": "synthetic-clip-2",
                                                    "partition": "train",
                                                    "group_ref": "synthetic-creator-1"})
            (root / "manifest.json").write_text(json.dumps(duplicate))
            (root / "annotations" / "2.json").write_text(json.dumps(third))
            with self.assertRaisesRegex(ValueError, "Grouped sources"):
                load_dataset(root)

    def test_missing_split_duplicate_annotator_and_bad_annotation(self):
        manifest, records = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_dataset(root, manifest, records)
            manifest["split_assignments"] = []
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "split"):
                load_dataset(root)
            manifest, records = fixture()
            (root / "manifest.json").write_text(json.dumps(manifest))
            records[1]["annotator_ref"] = records[0]["annotator_ref"]
            (root / "annotations" / "1.json").write_text(json.dumps(records[1]))
            with self.assertRaisesRegex(ValueError, "Duplicate annotator"):
                load_dataset(root)
            records[1]["techniques"][0]["technique_id"] = "invalid.technique"
            (root / "annotations" / "1.json").write_text(json.dumps(records[1]))
            result = subprocess.run([sys.executable, "-m", "intelligence.evaluation", "validate",
                                     str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid dataset", result.stderr)


if __name__ == "__main__":
    unittest.main()
