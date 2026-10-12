"""Small synthetic Stage 7.3 evaluation and fail-closed regression set."""

from copy import deepcopy
import unittest

from intelligence.creative_hypotheses import (
    Proposal, ProposalBatch, deterministic_baseline, run_one_call,
)
from intelligence.cross_video_content import run_one_pass
from test_stage7_2_cross_video_content import analysis, case_for, draft, ask_with, stage6_report


def source(descriptions, *, high=("p0", "p1", "p2"), low=(), metric="ctr"):
    content = None
    if any("earlier" in description for description in descriptions):
        content = {key: analysis(transcript="Spoken offer", at=2 if key in high else 8)
                   for key in ("p0", "p1", "p2", "p3", "p4", "p5")}
    case = case_for(metric=metric, content=content)
    if any("product visible" in description.casefold() for description in descriptions):
        for packet in case["packets"]:
            packet["frames"] = [{"ref": f"{packet['video_ref']}:frame:0",
                                 "timestamp_seconds": 0.5, "jpeg_sha256": "synthetic",
                                 "selection_reason": "opening"}]
            packet["gaps"].remove("source_media_unavailable")
    rows = []
    for description in descriptions:
        kind = ("frame" if "product visible" in description.casefold() else
                "ocr" if "visible text" in description.casefold() else "transcript")
        rows.append(draft(case, high, low, description=description, kind=kind).patterns[0])
    if content:
        rows[0].lower_support = draft(case, (), ("p3", "p4", "p5")).patterns[0].lower_support
        rows[0].temporal_relation = "earlier_in_higher"
    from intelligence.cross_video_content import ComparisonDraft
    result = run_one_pass(case, ask=ask_with(ComparisonDraft(
        patterns=rows, similarities=[], evidence_gaps=[])))
    return result, stage6_report(metric=metric)


def proposal(index=0, **changes):
    fields = dict(source_index=index,
        hypothesis="Test whether product visibility is associated with a different CTR under comparable delivery.",
        variable_to_test="product visibility", control_condition="Product appears after the opening.",
        variant_condition="Product is visible in the opening section.",
        limitations=["Delivery may still differ between variants."])
    fields.update(changes)
    return Proposal(**fields)


def ask(batch):
    def call(instructions, payload, images, schema, *, model, api_key):
        assert schema is ProposalBatch and not images
        assert len(payload["candidates"]) <= 4
        return batch, {"model": model, "elapsed_seconds": 0.01,
                       "input_tokens": 100, "output_tokens": 50}
    return call


class CreativeHypothesisTests(unittest.TestCase):
    def test_twelve_scenario_baseline_matrix(self):
        scenarios = [
            ("clean", ["Product visible in opening among higher-CTR videos."], ("p0", "p1", "p2"), (), 1),
            ("counterexample", ["Product visible in opening among higher-CTR videos."], ("p0", "p1", "p2"), ("p3",), 1),
            ("two_vs_zero", ["Product visible in opening among higher-CTR videos."], ("p0", "p1"), (), 1),
            ("weak", ["Product visible in opening among higher-CTR videos."], ("p0", "p1"), ("p3",), 0),
            ("non_actionable", ["The videos feel more engaging."], ("p0", "p1", "p2"), (), 0),
            ("vague", ["Production quality seems better."], ("p0", "p1", "p2"), (), 0),
            ("timing", ["Spoken offer appears earlier in the higher-CTR group."], ("p0", "p1", "p2"), (), 1),
            ("lower_cpc", ["Product visible in opening among lower-CPC videos."], (), ("p0", "p1", "p2"), 1),
            ("two", ["Product visible in opening.", "Spoken offer appears in opening."], ("p0", "p1", "p2"), (), 2),
            ("four_cap", ["Product visible in opening.", "Spoken offer appears in opening.",
                          "Visible text appears in opening.", "CTA appears in opening."], ("p0", "p1", "p2"), (), 3),
            ("scene_only", ["Scene boundaries differ."], ("p0", "p1", "p2"), (), 0),
        ]
        for name, descriptions, high, low, expected in scenarios:
            with self.subTest(name=name):
                metric = "cpc" if name == "lower_cpc" else "ctr"
                report, performance = source(descriptions, high=high, low=low, metric=metric)
                result = deterministic_baseline(report, performance)
                self.assertEqual(len(result["hypotheses"]), expected)
                self.assertEqual(result["metric_id"], metric)
                self.assertTrue(all(h["primary_metric"] == metric for h in result["hypotheses"]))
                if name == "counterexample":
                    self.assertEqual(result["hypotheses"][0]["support"]["lower_group_support"], 1)
                    self.assertEqual(len(result["hypotheses"][0]["counterevidence"]), 1)
                if name == "clean":
                    self.assertEqual(result["hypotheses"][0]["priority"], "strong_candidate")

    def test_one_call_grounded_and_no_forbidden_inputs(self):
        report, performance = source(["Product visible in opening among higher-CTR videos."], low=("p3",))
        seen = []
        def captured(instructions, payload, images, schema, *, model, api_key):
            seen.append(payload)
            return ask(ProposalBatch(hypotheses=[proposal()], abstentions=[]))(
                instructions, payload, images, schema, model=model, api_key=api_key)
        result = run_one_call(report, performance, ask=captured)
        self.assertEqual(len(seen), 1)
        self.assertEqual(result["provenance"]["model_calls"], 1)
        self.assertEqual(result["hypotheses"][0]["support"]["lower_group_support"], 1)
        self.assertEqual(len(result["hypotheses"][0]["counterevidence"]), 1)
        self.assertNotIn("motion_events", str(seen))
        self.assertNotIn("semantic_labels", str(seen))
        self.assertNotIn("recommendations", str(seen))
        self.assertNotIn("cpc", str(seen))

    def test_reject_causal_numbers_bad_design_and_bad_source(self):
        report, performance = source(["Product visible in opening among higher-CTR videos."])
        bad = [proposal(hypothesis="Product visibility improves CTR."),
               proposal(variant_condition="Run for 7 days."),
               proposal(control_condition="Product is visible in the opening section."),
               proposal(variable_to_test="production quality"),
               proposal(hypothesis="Test whether product visibility changes CPC."),
               proposal(source_index=9)]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                run_one_call(report, performance,
                             ask=ask(ProposalBatch(hypotheses=[item], abstentions=[])))
        with self.assertRaisesRegex(ValueError, "Too many"):
            run_one_call(report, performance, ask=ask(ProposalBatch(
                hypotheses=[proposal() for _ in range(4)], abstentions=[])))

    def test_missing_evidence_and_context_are_rejected(self):
        report, performance = source(["Product visible in opening among higher-CTR videos."])
        missing = deepcopy(report)
        missing["observed_differences"][0]["evidence_refs"][0]["evidence_ref"] = "absent"
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            deterministic_baseline(missing, performance)
        changed_count = deepcopy(report)
        changed_count["observed_differences"][0]["higher_group_support"] = 2
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            deterministic_baseline(changed_count, performance)
        mismatch = deepcopy(report)
        mismatch["context_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metric/context"):
            deterministic_baseline(mismatch, performance)


if __name__ == "__main__":
    unittest.main()
