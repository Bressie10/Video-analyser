"""Offline validation of the experimental V8.5 data contracts."""

import json
import unittest
from datetime import datetime, timezone
from importlib.resources import files

from pydantic import ValidationError

from intelligence.ontology import ID_PATTERN, Technique, techniques
from intelligence.schemas.annotation import Annotation, AnnotationDataset
from intelligence.schemas.benchmark import BenchmarkVideo
from intelligence.schemas.report import AnalysisReport
from intelligence.versions import (
    ANALYSIS_REPORT_VERSION, ANNOTATION_VERSION, BENCHMARK_VERSION, ONTOLOGY_VERSION,
)


NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
SOURCE = {"source_kind": "reference", "reference_id": "video-1", "platform": None,
          "duration_seconds": 21.2}
DETECTOR = {"name": "human-fixture", "version": "0.1.0"}
EVIDENCE = [{"kind": "transcript", "reference": "segment:0", "detail": None}]


def report():
    return {
        "schema_version": ANALYSIS_REPORT_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "source": SOURCE,
        "detector_versions": [DETECTOR],
        "techniques": [
            {"technique_id": "hook.question", "start_seconds": 0.2, "end_seconds": 1.8,
             "confidence": 0.9, "detector": DETECTOR, "evidence": EVIDENCE},
            {"technique_id": "editing.jump_cut", "start_seconds": 2.0, "end_seconds": None,
             "confidence": 0.8, "detector": DETECTOR, "evidence": EVIDENCE},
        ],
        "structure": [
            {"role": role, "start_seconds": start, "end_seconds": end,
             "confidence": 0.8, "detector": DETECTOR, "evidence": EVIDENCE}
            for role, start, end in [("hook", 0.0, 2.1), ("value", 2.1, 18.7),
                                     ("cta", 18.7, 21.2)]
        ],
        "derived_features": [
            {"feature_id": "cuts_first_5_seconds", "value": 4.0, "unit": "count",
             "window": {"start_seconds": 0.0, "end_seconds": 5.0}, "evidence_refs": []},
            {"feature_id": "average_shot_length_seconds", "value": 1.3, "unit": "seconds",
             "window": None, "evidence_refs": []},
            {"feature_id": "words_per_second", "value": 2.6, "unit": "words/second",
             "window": None, "evidence_refs": []},
        ],
        "limitations": ["Fixture only"],
        "provenance": {"run_id": "fixture-1", "processed_at": NOW,
                       "pipeline_version": "fixture-0.1", "input_sha256": None},
    }


def annotation(ref="annotation-1", annotator="annotator-a"):
    return {
        "schema_version": ANNOTATION_VERSION, "ontology_version": ONTOLOGY_VERSION,
        "annotation_ref": ref, "annotator_ref": annotator, "source": SOURCE,
        "techniques": [{"technique_id": "hook.question", "start_seconds": 0.2,
                        "end_seconds": 1.8, "note": None}],
        "structure": [{"role": "hook", "start_seconds": 0.0,
                       "end_seconds": 2.1, "note": None}],
        "numeric_ground_truth": [{"feature_id": "cuts_first_5_seconds", "value": 4.0,
                                  "unit": "count", "window": None, "evidence_refs": []}],
        "notes": None,
    }


def benchmark():
    return {
        "schema_version": BENCHMARK_VERSION,
        "source": {"platform": "instagram", "provider_identifier": "123", "public_url": None,
                   "reference": "benchmark-1", "acquisition_method": "manual reference",
                   "fetched_at": NOW},
        "creator": {"account_identifier": None, "account_url": None,
                    "follower_count": None, "follower_count_observed_at": None},
        "publication": {"published_at": None, "content_type": None, "declared_format": None},
        "performance": {"fetched_at": NOW, "source": "public page", "exposure": "unknown",
                        "metrics": {"view_count": None, "like_count": 12},
                        "metric_definitions": {}, "observation_window_start": None,
                        "observation_window_end": None, "attribution_context": None},
        "analysis": None, "baseline": None, "provenance_notes": [],
    }


class IntelligenceContractTests(unittest.TestCase):
    def test_ontology_metadata_and_ids(self):
        raw = json.loads(files("intelligence.ontology").joinpath("techniques.json").read_text())
        ids = [item["id"] for item in raw["techniques"]]
        self.assertEqual(len(ids), len(set(ids)))
        entries = techniques()
        self.assertEqual(set(entries), set(ids))
        self.assertEqual({item.category for item in entries.values()},
                         {"hook", "format", "editing", "text", "structure", "audio", "cta", "visual"})
        self.assertTrue(all(ID_PATTERN.fullmatch(item.id) for item in entries.values()))
        self.assertTrue(all(item.name and item.description and item.introduced_in
                            and isinstance(item.overlaps_allowed, bool) for item in entries.values()))
        invalid = entries["hook.question"].model_dump()
        invalid["id"] = "Hook.Bad"
        with self.assertRaises(ValidationError):
            Technique.model_validate(invalid)

    def test_report_round_trip_and_separate_features(self):
        parsed = AnalysisReport.model_validate(report())
        again = AnalysisReport.model_validate_json(parsed.model_dump_json())
        self.assertEqual(again, parsed)
        self.assertEqual([o.technique_id for o in again.techniques],
                         ["hook.question", "editing.jump_cut"])
        self.assertEqual(again.derived_features[0].feature_id, "cuts_first_5_seconds")
        self.assertEqual(again.structure[-1].role, "cta")

    def test_invalid_confidence_timing_and_technique_fail(self):
        for mutate in (
            lambda data: data["techniques"][0].update(confidence=1.1),
            lambda data: data["techniques"][0].update(confidence=-0.1),
            lambda data: data["techniques"][0].update(end_seconds=0.1),
            lambda data: data["techniques"][0].update(end_seconds=None),
            lambda data: data["techniques"][0].update(technique_id="editing.unknown"),
            lambda data: data["structure"][0].update(end_seconds=22.0),
            lambda data: data["derived_features"][0]["window"].update(end_seconds=22.0),
        ):
            with self.subTest(mutate=mutate):
                data = report()
                mutate(data)
                with self.assertRaises(ValidationError):
                    AnalysisReport.model_validate(data)

    def test_versions_are_required_and_independent(self):
        for field in ("schema_version", "ontology_version"):
            data = report()
            del data[field]
            with self.assertRaises(ValidationError):
                AnalysisReport.model_validate(data)
        data = report()
        data["detector_versions"][0] = {"name": "human-fixture", "version": "0.2.0"}
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)
        for builder, parser in ((annotation, Annotation), (benchmark, BenchmarkVideo)):
            data = builder()
            del data["schema_version"]
            with self.assertRaises(ValidationError):
                parser.model_validate(data)
        data = report()
        data["ontology_version"] = "2.0.0"
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)

    def test_annotations_round_trip_and_multiple_labelers(self):
        first = Annotation.model_validate(annotation())
        self.assertEqual(Annotation.model_validate_json(first.model_dump_json()), first)
        dataset = AnnotationDataset.model_validate({"annotations": [
            annotation(), annotation("annotation-2", "annotator-b")]})
        self.assertEqual(len(dataset.annotations), 2)
        self.assertEqual(dataset.annotations[0].source, dataset.annotations[1].source)
        with self.assertRaises(ValidationError):
            AnnotationDataset.model_validate({"annotations": [annotation(), annotation()]})
        data = annotation()
        data["techniques"][0]["technique_id"] = "hook.unknown"
        with self.assertRaises(ValidationError):
            Annotation.model_validate(data)

    def test_benchmark_unknown_stays_unknown(self):
        parsed = BenchmarkVideo.model_validate(benchmark())
        again = BenchmarkVideo.model_validate_json(parsed.model_dump_json())
        self.assertIsNone(again.performance.metrics["view_count"])
        self.assertEqual(again.performance.metrics["like_count"], 12)
        self.assertIsInstance(again.performance.metrics["like_count"], int)
        self.assertNotIn("comment_count", again.performance.metrics)
        self.assertIsNone(again.baseline)
        data = benchmark()
        data["performance"] = None
        self.assertIsNone(BenchmarkVideo.model_validate(data).performance)
        data = benchmark()
        data["performance"]["metrics"]["view_count"] = -1.0
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)


if __name__ == "__main__":
    unittest.main()
