"""Offline validation of the experimental V8.5 data contracts."""

import json
import unittest
from datetime import datetime, timezone
from importlib.resources import files

from pydantic import ValidationError

from intelligence.ontology import ID_PATTERN, Technique, techniques, validate_ontology
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
        "producer_versions": [DETECTOR],
        "techniques": [
            {"technique_id": "hook.question", "start_seconds": 0.2, "end_seconds": 1.8,
             "confidence": 0.9, "detector": DETECTOR, "evidence": EVIDENCE},
            {"technique_id": "editing.jump_cut", "start_seconds": 2.0, "end_seconds": None,
             "confidence": 0.8, "detector": DETECTOR, "evidence": EVIDENCE},
        ],
        "structure": [
            {"role": role, "start_seconds": start, "end_seconds": end,
             "confidence": 0.8, "detector": DETECTOR, "evidence": EVIDENCE}
            for role, start, end in [("hook", 0.0, 2.1), ("explanation", 2.1, 18.7),
                                     ("cta", 18.7, 21.2)]
        ],
        "derived_features": [
            {"feature_id": "cuts_first_5_seconds", "value": 4.0, "unit": "count",
             "window": {"start_seconds": 0.0, "end_seconds": 5.0}, "evidence_refs": [],
             "producer": DETECTOR},
            {"feature_id": "average_shot_length_seconds", "value": 1.3, "unit": "seconds",
             "window": None, "evidence_refs": [], "producer": DETECTOR},
            {"feature_id": "words_per_second", "value": 2.6, "unit": "words/second",
             "window": None, "evidence_refs": [], "producer": DETECTOR},
        ],
        "limitations": ["Fixture only"],
        "provenance": {"run_id": "fixture-1", "processed_at": NOW,
                       "pipeline_version": "fixture-0.1", "input_sha256": None},
    }


def annotation(ref="annotation-1", annotator="annotator-a"):
    return {
        "schema_version": ANNOTATION_VERSION, "ontology_version": ONTOLOGY_VERSION,
        "annotation_ref": ref, "annotator_ref": annotator, "source": SOURCE,
        "guideline_version": "1.0.0", "annotated_at": NOW,
        "coverage": {"complete_technique_categories": ["hook"],
                     "structure_complete": True,
                     "numeric_fields": [{"feature_id": "cuts_first_5_seconds",
                                         "status": "measured", "note": None}]},
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
                        "metric_definitions": {
                            "view_count": {"description": "Public views", "unit": "count",
                                           "measurement_basis": "Public page display"},
                            "like_count": {"description": "Public likes", "unit": "count",
                                           "measurement_basis": "Public page display"}},
                        "observation_window_start": None,
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
        self.assertTrue({"editing.zoom", "editing.transition", "editing.picture_in_picture"} <= set(entries))
        self.assertNotIn("editing.cutaway", entries)
        invalid = entries["hook.question"].model_dump()
        invalid["id"] = "Hook.Bad"
        with self.assertRaises(ValidationError):
            Technique.model_validate(invalid)

    def test_ontology_additive_version_compatibility(self):
        old = techniques()["editing.jump_cut"].model_dump()
        added = techniques()["editing.zoom"].model_dump()
        data = {"ontology_version": "1.1.0", "techniques": [old, added]}
        self.assertEqual(set(validate_ontology(data, expected_version="1.1.0")),
                         {"editing.jump_cut", "editing.zoom"})
        self.assertEqual(set(validate_ontology({"ontology_version": "1.0.0",
                          "techniques": [old]}, expected_version="1.0.0")),
                         {"editing.jump_cut"})
        with self.assertRaises(ValueError):
            validate_ontology(data, expected_version="1.0.0")
        data["techniques"][1]["introduced_in"] = "1.2.0"
        with self.assertRaises(ValueError):
            validate_ontology(data, expected_version="1.1.0")
        data["ontology_version"] = "01.1.0"
        with self.assertRaises(ValueError):
            validate_ontology(data, expected_version="01.1.0")

    def test_report_round_trip_and_separate_features(self):
        parsed = AnalysisReport.model_validate(report())
        again = AnalysisReport.model_validate_json(parsed.model_dump_json())
        self.assertEqual(again, parsed)
        self.assertEqual([o.technique_id for o in again.techniques],
                         ["hook.question", "editing.jump_cut"])
        self.assertEqual(again.derived_features[0].feature_id, "cuts_first_5_seconds")
        self.assertEqual(again.derived_features[0].producer.version, "0.1.0")
        self.assertEqual(again.structure[-1].role, "cta")

    def test_derived_features_require_versioned_producer(self):
        data = report()
        del data["derived_features"][0]["producer"]
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)
        data = report()
        data["derived_features"][0]["producer"] = {"name": "human-fixture", "version": "0.2.0"}
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)
        data["producer_versions"].append({"name": "human-fixture", "version": "0.2.0"})
        self.assertEqual(AnalysisReport.model_validate(data).derived_features[0].producer.version,
                         "0.2.0")

    def test_structure_vocabulary_is_controlled(self):
        for role in ("hook", "setup", "problem", "explanation", "demonstration",
                     "proof", "payoff", "cta", "other"):
            data = report()
            data["structure"][0]["role"] = role
            AnalysisReport.model_validate(data)
            human = annotation()
            human["structure"][0]["role"] = role
            Annotation.model_validate(human)
        data = report()
        data["structure"][0]["role"] = "viral"
        with self.assertRaises(ValidationError):
            AnalysisReport.model_validate(data)

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
        data["producer_versions"][0] = {"name": "human-fixture", "version": "0.2.0"}
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

    def test_coverage_distinguishes_negative_from_unchecked(self):
        data = annotation()
        data["techniques"] = []
        data["coverage"]["complete_technique_categories"] = ["hook"]
        checked = Annotation.model_validate(data)
        self.assertEqual(checked.coverage.complete_technique_categories, ["hook"])
        data["coverage"]["complete_technique_categories"] = []
        unchecked = Annotation.model_validate(data)
        self.assertEqual(unchecked.coverage.complete_technique_categories, [])
        data["structure"] = []
        data["coverage"]["structure_complete"] = False
        self.assertFalse(Annotation.model_validate(data).coverage.structure_complete)
        data["coverage"]["structure_complete"] = True
        self.assertTrue(Annotation.model_validate(data).coverage.structure_complete)
        data["coverage"]["complete_technique_categories"] = ["unknown"]
        with self.assertRaises(ValidationError):
            Annotation.model_validate(data)
        data = annotation()
        data["coverage"]["numeric_fields"] = []
        with self.assertRaises(ValidationError):
            Annotation.model_validate(data)
        data = annotation()
        data["numeric_ground_truth"] = []
        data["coverage"]["numeric_fields"][0] = {
            "feature_id": "cuts_first_5_seconds", "status": "unavailable", "note": "Audio only"}
        self.assertEqual(Annotation.model_validate(data).coverage.numeric_fields[0].status,
                         "unavailable")

    def test_human_provenance_and_same_source_identity(self):
        data = annotation()
        del data["guideline_version"]
        with self.assertRaises(ValidationError):
            Annotation.model_validate(data)
        data = annotation()
        data["annotated_at"] = datetime(2026, 10, 4)
        with self.assertRaises(ValidationError):
            Annotation.model_validate(data)
        second = annotation("annotation-2", "annotator-b")
        second["techniques"] = []
        AnnotationDataset.model_validate({"annotations": [annotation(), second]})
        second["source"] = {**SOURCE, "duration_seconds": 22.0}
        with self.assertRaises(ValidationError):
            AnnotationDataset.model_validate({"annotations": [annotation(), second]})

    def test_source_level_splits_prevent_annotation_leakage(self):
        records = [annotation(), annotation("annotation-2", "annotator-b")]
        split = {"source_ref": "video-1", "partition": "test", "group_ref": "creator-1"}
        dataset = AnnotationDataset.model_validate({"annotations": records,
                                                     "split_assignments": [split]})
        self.assertEqual(len(dataset.split_assignments), 1)
        with self.assertRaises(ValidationError):
            AnnotationDataset.model_validate({"annotations": records,
                                              "split_assignments": [split, {**split, "partition": "train"}]})
        other = annotation("annotation-3", "annotator-c")
        other["source"] = {**SOURCE, "reference_id": "video-2"}
        with self.assertRaises(ValidationError):
            AnnotationDataset.model_validate({"annotations": [*records, other],
                "split_assignments": [split, {"source_ref": "video-2", "partition": "train",
                                              "group_ref": "creator-1"}]})

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

    def test_metric_definitions_and_baseline_context_are_required(self):
        data = benchmark()
        del data["performance"]["metric_definitions"]["like_count"]
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)
        data = benchmark()
        del data["performance"]["metric_definitions"]["view_count"]
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)
        data = benchmark()
        data["performance"]["metric_definitions"]["like_count"]["measurement_basis"] = ""
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)
        data = benchmark()
        data["baseline"] = {"source": "account export", "metrics": {"view_count": 150},
            "metric_definitions": {"view_count": {"description": "Account post views",
                "unit": "count", "measurement_basis": "Account export"}},
            "sample_size": 20, "window_start": NOW,
            "window_end": datetime(2026, 10, 5, tzinfo=timezone.utc),
            "cohort_definition": "Previous 20 organic reels", "method_reference": "median per post"}
        self.assertEqual(BenchmarkVideo.model_validate(data).baseline.sample_size, 20)
        del data["baseline"]["cohort_definition"]
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)
        data = benchmark()
        data["baseline"] = {"source": "account export", "metrics": {"view_count": 150},
            "metric_definitions": {"view_count": {"description": "Account post views",
                "unit": "count", "measurement_basis": "Account export"}},
            "sample_size": 0, "window_start": NOW,
            "window_end": datetime(2026, 10, 5, tzinfo=timezone.utc),
            "cohort_definition": "Previous organic reels", "method_reference": "median per post"}
        with self.assertRaises(ValidationError):
            BenchmarkVideo.model_validate(data)


if __name__ == "__main__":
    unittest.main()
