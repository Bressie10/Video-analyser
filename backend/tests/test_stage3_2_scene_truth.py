import json
import tempfile
import unittest
from pathlib import Path

from intelligence.evaluation.stage3_2_scene_truth import repair


class SceneTruthRepairTest(unittest.TestCase):
    def test_replaces_only_scored_scene_truth_and_backs_up_all_records(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            truth_dir, backup_dir = root / "truth", root / "backup"
            truth_dir.mkdir()
            originals = {}
            for ref in ("01", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"):
                record = {
                    "low_level_truth_version": "1.0.0", "source_ref": ref,
                    "record_kind": "reviewed", "reviewer_ref": "pilot",
                    "reviewed_at": "2026-10-10T00:00:00Z", "notes": "Gemini provisional",
                    "coverage": {"scene_boundaries": "complete", "ocr": "partial",
                                 "transcript": "unavailable", "motion": "unavailable",
                                 "metadata": "unavailable"},
                    "observations": {"scene_boundaries": [], "ocr": [{"text": "keep"}]},
                }
                path = truth_dir / f"{ref}.json"
                path.write_text(json.dumps(record))
                originals[path.name] = path.read_bytes()
            annotations = {ref: {"boundaries": [{"time_seconds": time}],
                                 "ambiguous": [{"time_seconds": 3.0}] if ref == "07" else []}
                           for ref, time in (("04", 2.0), ("07", 4.0), ("09", 6.0))}
            annotation_path = root / "annotations.json"
            annotation_path.write_text(json.dumps(annotations))

            repair(truth_dir, backup_dir, annotation_path,
                   {ref: 10.0 for ref in annotations})

            self.assertEqual({path.name: path.read_bytes() for path in backup_dir.glob("*.json")},
                             originals)
            for ref, time in (("04", 2.0), ("07", 4.0), ("09", 6.0)):
                updated = json.loads((truth_dir / f"{ref}.json").read_text())
                original = json.loads(originals[f"{ref}.json"])
                self.assertEqual(updated["observations"]["scene_boundaries"],
                                 [{"time_seconds": time}])
                self.assertEqual(updated["observations"]["ocr"], original["observations"]["ocr"])
                self.assertEqual(updated["coverage"], original["coverage"])
                self.assertIn("not fully blinded", updated["notes"])
            self.assertEqual((truth_dir / "01.json").read_bytes(), originals["01.json"])

    def test_rejects_missing_annotation_before_writing(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            truth_dir = root / "truth"
            truth_dir.mkdir()
            annotation_path = root / "annotations.json"
            annotation_path.write_text(json.dumps({"04": {"boundaries": [], "ambiguous": []}}))
            with self.assertRaisesRegex(ValueError, "exactly"):
                repair(truth_dir, root / "backup", annotation_path, {})
            self.assertFalse((root / "backup").exists())


if __name__ == "__main__":
    unittest.main()
