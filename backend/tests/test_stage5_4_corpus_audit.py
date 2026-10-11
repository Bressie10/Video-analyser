"""Truth-free scale-out audit checks."""

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligence.evaluation.stage5_4_corpus_audit import audit


class Stage54CorpusAuditTests(unittest.TestCase):
    def test_existing_candidate_passes_and_corrupt_contract_is_flagged(self):
        path = Path(__file__).resolve().parents[1] / (
            "intelligence/evaluation/stage5_4/candidates/01.json")
        candidate = json.loads(path.read_text())
        candidate["content_sha256"] = hashlib.sha256(b"{}").hexdigest()
        low_level = {"analysis": {"metadata": {"duration_seconds":
                     candidate["analysis_report"]["source"]["duration_seconds"]}}}
        with patch("intelligence.evaluation.stage5_4_corpus_audit.semantic_input", return_value={}), \
             patch("intelligence.evaluation.stage5_4_corpus_audit.ledger_failures", return_value=[]):
            self.assertEqual(audit("01", candidate, low_level)["failures"], [])
            broken = copy.deepcopy(candidate)
            broken["semantic_draft"]["findings"][0]["technique_id"] = "invalid.label"
            broken["semantic_draft"]["findings"][0]["start_seconds"] = -1
            failures = audit("01", broken, low_level)["failures"]
        self.assertIn("invalid ontology ID", failures)
        self.assertIn("impossible finding timestamp", failures)


if __name__ == "__main__":
    unittest.main()
