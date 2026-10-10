"""Focused tests for the offline V9 OCR evaluation scores."""

import unittest

from intelligence.evaluation.stage1 import _score_ocr, aggregate, evaluate_one
from test_stage1_calibration import synthetic_analysis, synthetic_truth


def prediction(text, start=0, end=2):
    return {"text": text, "appearance_timestamp_seconds": start,
            "disappearance_timestamp_seconds": end}


def truth_span(text, start=0, end=2):
    return {"text": text, "normalized_text": text,
            "start_seconds": start, "end_seconds": end}


class OcrEvaluationTests(unittest.TestCase):
    def score(self, predicted, truth):
        result = _score_ocr(predicted, truth, 0.5)
        self.assertEqual(result, _score_ocr(predicted, truth, 0.5))
        return result

    def test_split_barracat_phrase_preserves_strict_comparison(self):
        result = self.score([prediction("is inspired"), prediction("by Barracat Rouge")],
                            [truth_span("is inspired by Barracat Rouge")])
        self.assertEqual(result["exact_text"]["recall"], 0)
        self.assertEqual(result["exact_text_and_time"]["recall"], 0)
        self.assertEqual((result["normalized_text_precision"], result["normalized_text_recall"],
                          result["normalized_text_f1"], result["temporal_text_coverage"]),
                         (1, 1, 1, 1))

    def test_graphical_lines_grouped_in_one_truth_span(self):
        result = self.score([prediction("First line"), prediction("Second line"),
                             prediction("Third line")],
                            [truth_span("First line\nSecond line\nThird line")])
        self.assertEqual(result["normalized_text_token_counts"],
                         {"matched": 6, "predicted": 6, "truth": 6})
        self.assertEqual(result["temporal_text_coverage"], 1)

    def test_duplicate_predictions_are_counted_once(self):
        result = self.score([prediction("Hello world"), prediction("Hello world")],
                            [truth_span("Hello world")])
        self.assertEqual(result["normalized_text_precision"], 0.5)
        self.assertEqual(result["normalized_text_recall"], 1)
        self.assertEqual(result["normalized_text_f1"], 2 / 3)
        self.assertEqual(result["temporal_text_coverage_counts"]["matched"], 2)

    def test_overlapping_subtitle_and_overlay_and_grouped_prediction(self):
        truth = [truth_span("Follow us"), truth_span("The story starts here")]
        result = self.score([prediction("Follow us The story starts here")], truth)
        self.assertEqual(result["temporal_text_coverage"], 1)
        self.assertEqual(result["temporal_text_coverage_counts"]["matched"], 6)
        # One short prediction cannot count twice against two concurrent spans.
        duplicate_truth = self.score([prediction("Follow us")],
                                     [truth_span("Follow us"), truth_span("Follow us")])
        self.assertEqual(duplicate_truth["temporal_text_coverage"], 0.5)

    def test_unrelated_text_at_same_time_gets_no_coverage(self):
        result = self.score([prediction("Subscribe now")], [truth_span("Barracat Rouge")])
        self.assertEqual(result["normalized_text_recall"], 0)
        self.assertEqual(result["temporal_text_coverage"], 0)
        self.assertEqual(result["unmatched_visible_text_span_rate"], 0)

    def test_case_unicode_whitespace_and_punctuation(self):
        result = self.score([prediction("  IS   inspired — by BARRACAT, Rouge! ")],
                            [truth_span("is inspired by Barracat Rouge")])
        self.assertEqual(result["normalized_text_f1"], 1)
        self.assertEqual(result["temporal_text_coverage"], 1)
        self.assertEqual(result["exact_text"]["recall"], 1)
        compatibility = self.score([prediction("Ｆｏｌｌｏｗ us")], [truth_span("follow us")])
        self.assertEqual(compatibility["normalized_text_f1"], 1)

    def test_time_overlap_required_and_partial_truth_abstains(self):
        result = self.score([prediction("Follow us", 3, 4)], [truth_span("Follow us", 0, 2)])
        self.assertEqual(result["normalized_text_recall"], 1)
        self.assertEqual(result["temporal_text_coverage"], 0)
        analysis, truth = synthetic_analysis(), synthetic_truth()
        truth["coverage"]["ocr"] = "partial"
        self.assertEqual(evaluate_one(analysis, truth)["ocr"],
                         {"status": "abstained", "reason": "partial"})

    def test_aggregate_uses_token_denominators(self):
        first = evaluate_one(synthetic_analysis(), synthetic_truth())
        second_analysis, second_truth = synthetic_analysis(), synthetic_truth("synthetic-1")
        second_analysis["on_screen_text"] = [prediction("unrelated", 0.5, 4)]
        second = evaluate_one(second_analysis, second_truth)
        rows = {"a": {"status": "evaluated", "signals": first},
                "b": {"status": "evaluated", "signals": second}}
        result = aggregate(rows)["ocr"]
        self.assertEqual(result["normalized_text_token_counts"],
                         {"matched": 2, "predicted": 3, "truth": 4})
        self.assertEqual(result["normalized_text_precision"], 2 / 3)
        self.assertEqual(result["normalized_text_recall"], 0.5)
        self.assertEqual(result["temporal_text_coverage"], 0.5)


if __name__ == "__main__":
    unittest.main()
