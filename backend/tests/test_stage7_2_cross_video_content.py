"""Synthetic Stage 7.2 grouping, grounding, and architecture probes."""

from copy import deepcopy
from unittest.mock import patch
import unittest

from intelligence.performance_comparison import compare
from intelligence.cross_video_content import (
    Citation, ComparisonDraft, Pattern, content_packet,
    construct_groups, prepare_case, run_one_pass,
)


VALUES = {"p0": "60", "p1": "50", "p2": "40", "p3": "30", "p4": "20", "p5": "10"}


def paid(provider, *, ctr=None, cpc=None):
    details = {"date_start": "2026-01-01", "date_stop": "2026-01-07",
               "account_currency": "EUR", "action_report_time": "impression",
               "action_attribution_windows": ["7d_click", "1d_view"],
               "impressions": 1000, "reach": 500, "clicks": 20,
               "spend": "10", "ctr": ctr or VALUES[provider],
               "cpc": cpc or VALUES[provider]}
    return {"reference": f"synthetic-{provider}", "provider_id": provider,
            "public_url": None, "workspace_id": "synthetic-workspace",
            "platform": "meta_all_placements", "performance_source": "meta_ads",
            "exposure_type": "paid", "account_id": "synthetic-account",
            "fetched_at": "2026-01-08T00:00:00+00:00",
            "performance_metrics": {"meta_ads": details}}


def stage6_report(*, metric="ctr", values=None, second_metric=False):
    values = values or VALUES
    records = [paid(key, ctr=values[key], cpc=str(70 - int(values[key]))) for key in VALUES]
    return compare(records[0], records[1:], [metric, "cpc"] if second_metric else [metric])


def analysis(*, transcript="Setup", at=1.0, ocr="Label"):
    return {"metadata": {"duration_seconds": 12, "video": {"width": 640, "height": 480}},
            "audio": {"segments": [{"start": at, "end": at + 1, "text": transcript}]},
            "on_screen_text": ([{"appearance_timestamp_seconds": at,
                                 "disappearance_timestamp_seconds": at + 2,
                                 "text": ocr}] if ocr is not None else []),
            "scenes": [{"start_seconds": 0, "end_seconds": 12}],
            "motion_events": [{"type": "camera_pan"}],
            "semantic_labels": ["unsupported"], "recommendations": "ignore"}


def case_for(*, media=None, content=None, metric="ctr", report=None):
    report = report or stage6_report(metric=metric)
    content = content or {key: analysis(transcript="Product" if key in ("p0", "p1", "p2")
                                else "Setup") for key in VALUES}
    return prepare_case(report, metric, content, media)


def citations(case, providers, kind="transcript"):
    kind = {"frame": "frames", "scene": "scenes"}.get(kind, kind)
    members = {row["provider_id"]: row["video_ref"] for row in
               case["groups"]["higher_metric_group"] + case["groups"]["lower_metric_group"]}
    packets = {packet["video_ref"]: packet for packet in case["packets"]}
    return [Citation(video_ref=members[provider],
                     evidence_ref=packets[members[provider]][kind][0]["ref"])
            for provider in providers]


def draft(case, high=("p0", "p1", "p2"), low=(), *, kind="transcript",
          description="Product is named more often in the higher-CTR group.", temporal="none"):
    return ComparisonDraft(patterns=[Pattern(description=description, evidence_type=kind,
        higher_support=citations(case, high, kind), lower_support=citations(case, low, kind),
        counterexamples=citations(case, low, kind) if low else [],
        temporal_relation=temporal)], similarities=[], evidence_gaps=[])


def ask_with(result):
    def ask(instructions, payload, images, schema, *, model, api_key):
        return result, {"model": model, "response_id": "synthetic-response",
                        "prompt_sha256": "synthetic", "elapsed_seconds": 0,
                        "input_tokens": None, "output_tokens": None}
    return ask


class CrossVideoContentTests(unittest.TestCase):
    def test_grouping_one_lens_distinct_objects_and_ties(self):
        report = stage6_report(second_metric=True)
        ctr = construct_groups(report, "ctr")
        cpc = construct_groups(report, "cpc")
        self.assertEqual([x["provider_id"] for x in ctr["higher_metric_group"]], ["p0", "p1", "p2"])
        self.assertEqual([x["provider_id"] for x in ctr["lower_metric_group"]], ["p5", "p4", "p3"])
        self.assertEqual([x["provider_id"] for x in cpc["lower_metric_group"]], ["p0", "p1", "p2"])
        self.assertEqual(ctr["metric_id"], "ctr")
        self.assertTrue(all(row["context_fingerprint"] == ctr["context_fingerprint"]
                            for row in ctr["higher_metric_group"] + ctr["lower_metric_group"]))
        tied = stage6_report(values={**VALUES, "p2": "30"})
        with self.assertRaisesRegex(ValueError, "cutoff tie"):
            construct_groups(tied, "ctr")
        insufficient = compare(paid("p0"), [paid(key) for key in ("p1", "p2", "p3", "p4")], ["ctr"])
        with self.assertRaises(ValueError):
            construct_groups(insufficient, "ctr")

    def test_latest_or_duplicate_provider_is_rejected(self):
        report = stage6_report()
        report["deduplicated_records"]["ctr"] = [{"reason": "older_version"}]
        with self.assertRaisesRegex(ValueError, "latest versions"):
            construct_groups(report, "ctr")
        report = stage6_report()
        report["metric_comparisons"][0]["peer_values"][1]["identity"]["provider_id"] = "p1"
        with self.assertRaisesRegex(ValueError, "duplicated"):
            construct_groups(report, "ctr")

    def test_raw_evidence_allowlist_and_visual_attachment(self):
        packet, images = content_packet("video_synthetic", analysis())
        self.assertEqual(images, [])
        self.assertEqual(packet["transcript"][0]["timestamp_seconds"], 1)
        self.assertIn("source_media_unavailable", packet["gaps"])
        self.assertNotIn("motion_events", str(packet))
        self.assertNotIn("semantic_labels", str(packet))
        self.assertNotIn("recommendations", str(packet))
        with patch("intelligence.evaluation.stage5_semantic.select_frame_timestamps",
                   return_value=[{"timestamp_seconds": 0.1, "reason": "opening"}]), patch(
                   "intelligence.evaluation.stage5_semantic.extract_frames",
                   return_value=([{"ref": "frame:0", "timestamp_seconds": 0.1,
                                   "selection_reason": "opening", "jpeg_sha256": "abc"}],
                                 [{"_jpeg": b"jpeg"}])):
            with patch("pathlib.Path.is_file", return_value=True):
                packet, images = content_packet("video_synthetic", analysis(), __import__("pathlib").Path("synthetic.mp4"))
        self.assertEqual(packet["frames"][0]["ref"], "video_synthetic:frame:0")
        self.assertEqual(images, [("video_synthetic:frame:0", b"jpeg")])

    def test_support_counterexamples_and_mixed_cases(self):
        case = case_for()
        scenarios = [
            ("obvious", ("p0", "p1", "p2"), (), 1, 0),
            ("one_video", ("p0",), (), 0, 1),
            ("two_vs_zero", ("p0", "p1"), (), 1, 0),
            ("two_vs_two", ("p0", "p1"), ("p3", "p4"), 0, 1),
            ("counterexample", ("p0", "p1", "p2"), ("p3",), 1, 0),
        ]
        for name, high, low, expected_patterns, expected_mixed in scenarios:
            with self.subTest(name=name):
                result = run_one_pass(case, ask=ask_with(draft(case, high, low)))
                self.assertEqual(len(result["observed_differences"]), expected_patterns)
                self.assertEqual(len(result["mixed_inconclusive"]), expected_mixed)
                if name == "counterexample":
                    self.assertEqual(result["observed_differences"][0]["lower_group_support"], 1)
                    self.assertEqual(len(result["observed_differences"][0]["counterexamples"]), 1)

    def test_missing_frames_and_ocr_demote_patterns(self):
        case = case_for()
        for packet in case["packets"]:
            if packet["video_ref"] != case["groups"]["lower_metric_group"][0]["video_ref"]:
                packet["frames"] = [{"ref": f"{packet['video_ref']}:frame:0",
                                     "timestamp_seconds": 1.0, "jpeg_sha256": "synthetic",
                                     "selection_reason": "opening"}]
        result = run_one_pass(case, ask=ask_with(draft(case, ("p0", "p1"), (), kind="frame")))
        self.assertEqual(result["observed_differences"], [])
        self.assertEqual(result["mixed_inconclusive"][0]["reason"], "incomplete_evidence_coverage")
        content = {key: analysis(ocr=None if key == "p5" else "Product") for key in VALUES}
        case = case_for(content=content)
        result = run_one_pass(case, ask=ask_with(draft(case, ("p0", "p1"), (), kind="ocr")))
        self.assertEqual(result["observed_differences"], [])
        self.assertTrue(any("ocr_unavailable" in gap for gap in result["evidence_gaps"]))

    def test_temporal_relation_requires_measured_gap(self):
        content = {key: analysis(transcript="Product", at=2 if key in ("p0", "p1", "p2") else 8)
                   for key in VALUES}
        case = case_for(content=content)
        result = run_one_pass(case, ask=ask_with(draft(case,
            ("p0", "p1", "p2"), ("p3", "p4", "p5"),
            description="Product is named earlier in the higher-CTR group.",
            temporal="earlier_in_higher")))
        self.assertEqual(result["observed_differences"][0]["timing"]["higher_median_seconds"], 2)
        self.assertEqual(result["observed_differences"][0]["timing"]["lower_median_seconds"], 8)
        self.assertEqual(result["observed_differences"][0]["higher_group_support"], 3)
        swapped = deepcopy(case)
        for packet in swapped["packets"]:
            packet["transcript"][0]["timestamp_seconds"] = 5
        result = run_one_pass(swapped, ask=ask_with(draft(swapped,
            ("p0", "p1", "p2"), ("p3", "p4", "p5"),
            description="Product is named earlier in the higher-CTR group.",
            temporal="earlier_in_higher")))
        self.assertEqual(result["observed_differences"], [])

    def test_causal_advice_and_bad_citations_rejected(self):
        case = case_for()
        for sentence in ("Showing the product early increased CTR.",
                         "The hook drove clicks.", "Best practices suggest this format."):
            with self.subTest(sentence=sentence), self.assertRaises(ValueError):
                run_one_pass(case, ask=ask_with(draft(case, description=sentence)))
        for sentence in ("You should show the product early.",
                         "This format leads to more clicks.",
                         "Successful ads tend to use this opening."):
            with self.subTest(sentence=sentence), self.assertRaises(ValueError):
                run_one_pass(case, ask=ask_with(draft(case, description=sentence)))
        bad = draft(case)
        bad.patterns[0].higher_support[0].evidence_ref = "video_missing:transcript:0"
        with self.assertRaisesRegex(ValueError, "absent"):
            run_one_pass(case, ask=ask_with(bad))
        with self.assertRaisesRegex(ValueError, "Temporal wording"):
            run_one_pass(case, ask=ask_with(draft(case,
                description="Product appeared earlier in the higher group.")))
        bad_gap = ComparisonDraft(patterns=[], similarities=[], evidence_gaps=["This hook improved CTR."])
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            run_one_pass(case, ask=ask_with(bad_gap))

    def test_one_pass_uses_only_bounded_facts_and_raw_evidence(self):
        case = case_for()
        seen = []
        pattern = draft(case)
        def ask(instructions, payload, images, schema, *, model, api_key):
            seen.append((schema.__name__, payload))
            return pattern, {"model": model, "response_id": "comparison",
                "prompt_sha256": "synthetic", "elapsed_seconds": 0,
                "input_tokens": None, "output_tokens": None}
        single = run_one_pass(case, ask=ask)
        self.assertEqual(len(single["observed_differences"]), 1)
        self.assertEqual(single["provenance"]["model_calls"], 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "ComparisonDraft")
        payload = seen[0][1]
        self.assertEqual(payload["metric"]["metric_id"], "ctr")
        self.assertEqual(len(payload["videos"]), 6)
        self.assertNotIn("semantic_labels", str(payload))
        self.assertNotIn("motion_events", str(payload))
        self.assertNotIn("recommendations", str(payload))

    def test_transcript_ocr_disagreement_is_not_forced_into_pattern(self):
        content = {key: analysis(transcript="Spoken offer", ocr="Different on-screen label")
                   for key in VALUES}
        case = case_for(content=content)
        candidate = ComparisonDraft(patterns=[], similarities=[],
                                    evidence_gaps=["Transcript and OCR describe different text; relation unclear."])
        result = run_one_pass(case, ask=ask_with(candidate))
        self.assertEqual(result["observed_differences"], [])
        self.assertTrue(any("relation unclear" in gap for gap in result["evidence_gaps"]))
