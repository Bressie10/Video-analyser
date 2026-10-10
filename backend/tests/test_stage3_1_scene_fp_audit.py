import copy
import json
import unittest
from pathlib import Path

from intelligence.evaluation.stage3_1_audit import markdown, validate

ROOT = Path(__file__).resolve().parents[1] / "intelligence" / "evaluation" / "stage3"


class SceneFalsePositiveAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads((ROOT / "scene_fp_audit.json").read_text())
        cls.sweep = json.loads((ROOT / "scene_threshold_sweep.json").read_text())

    def test_every_unmatched_cut_is_inspected_once(self):
        validate(self.audit, self.sweep)
        self.assertEqual(self.audit["summary"]["inspected_events"], 102)
        self.assertEqual([sum(event["source_ref"] == ref for event in self.audit["events"])
                          for ref in ("04", "07", "09")], [47, 50, 5])
        self.assertEqual(self.audit["summary"]["truth_review_status"],
                         {"likely": 86, "possible": 11, "none": 5})
        self.assertIn("15.000 s", markdown(self.audit))

    def test_missing_or_misaligned_frame_evidence_is_rejected(self):
        changed = copy.deepcopy(self.audit)
        changed["events"][0]["sample_timestamps_seconds"]["+0.05"] += 0.1
        with self.assertRaisesRegex(ValueError, "Frame sample mismatch"):
            validate(changed, self.sweep)
        changed = copy.deepcopy(self.audit)
        changed["events"].pop()
        with self.assertRaisesRegex(ValueError, "Missing inspected cuts"):
            validate(changed, self.sweep)

    def test_suspected_truth_error_list_is_derived_from_decisions(self):
        changed = copy.deepcopy(self.audit)
        changed["suspected_truth_errors"]["likely"].pop()
        with self.assertRaisesRegex(ValueError, "Suspected truth error list differs"):
            validate(changed, self.sweep)


if __name__ == "__main__":
    unittest.main()
