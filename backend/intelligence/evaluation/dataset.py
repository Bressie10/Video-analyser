"""File based evaluation dataset checks; contract validation remains in schemas."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from intelligence.ontology import AREAS, techniques
from intelligence.schemas.annotation import Annotation, AnnotationDataset, SourceSplit


def load_dataset(directory: str | Path) -> tuple[AnnotationDataset, dict]:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text())
    if set(manifest) != {"sources", "split_assignments"}:
        raise ValueError("Manifest needs exactly sources and split_assignments")
    sources = manifest["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("Manifest sources must be a nonempty list")
    refs = [source["reference_id"] for source in sources]
    if len(refs) != len(set(refs)):
        raise ValueError("Duplicate source references in manifest")
    for source in sources:
        if set(source) != {"reference_id", "media_ref", "notes"}:
            raise ValueError("Source entry needs reference_id, media_ref and notes")
        if not isinstance(source["media_ref"], str) or not source["media_ref"].strip():
            raise ValueError("Each source needs an external or local media reference")
    media_refs = [source["media_ref"] for source in sources]
    if len(media_refs) != len(set(media_refs)):
        raise ValueError("Duplicate media references in manifest")
    paths = sorted((root / "annotations").glob("*.json"))
    if not paths:
        raise ValueError("No annotation JSON files found")
    annotations = [Annotation.model_validate_json(path.read_text()) for path in paths]
    splits = [SourceSplit.model_validate(item) for item in manifest["split_assignments"]]
    dataset = AnnotationDataset.model_validate({"annotations": annotations,
                                                "split_assignments": splits})
    if set(refs) != {annotation.source.reference_id for annotation in annotations}:
        raise ValueError("Manifest sources must match annotated sources exactly")
    # A future gold dataset always has an explicit partition and leakage group.
    if not splits or any(item.group_ref is None for item in splits):
        raise ValueError("Every source needs a split and a nonblank group_ref")
    by_source = defaultdict(list)
    for annotation in annotations:
        by_source[annotation.source.reference_id].append(annotation.annotator_ref)
    for ref, annotators in by_source.items():
        if len(annotators) != len(set(annotators)):
            raise ValueError(f"Duplicate annotator for source {ref}")
    return dataset, manifest


def summarize(dataset: AnnotationDataset) -> dict:
    annotations = dataset.annotations
    by_source = defaultdict(set)
    counts = Counter()
    covered = Counter()
    numeric = Counter()
    for item in annotations:
        by_source[item.source.reference_id].add(item.annotator_ref)
        counts.update(span.technique_id for span in item.techniques)
        covered.update(item.coverage.complete_technique_categories)
        covered.update(["structure_roles"] if item.coverage.structure_complete else [])
        numeric.update(field.status for field in item.coverage.numeric_fields)
    return {
        "annotations": len(annotations),
        "sources": len(by_source),
        "guideline_versions": dict(sorted(Counter(item.guideline_version for item in annotations).items())),
        "annotator_overlap": {ref: sorted(names) for ref, names in sorted(by_source.items())
                              if len(names) > 1},
        "coverage_counts": {area: covered[area] for area in sorted(AREAS)} |
                           {"structure_roles": covered["structure_roles"]},
        "missing_categories": {item.annotation_ref: sorted(AREAS -
                             set(item.coverage.complete_technique_categories)) for item in annotations
                             if AREAS - set(item.coverage.complete_technique_categories)},
        "incomplete_structure": [item.annotation_ref for item in annotations
                                 if not item.coverage.structure_complete],
        "numeric_status_counts": dict(sorted(numeric.items())),
        "label_frequencies": {key: counts[key] for key in sorted(techniques())},
        "splits": dict(sorted(Counter(item.partition for item in dataset.split_assignments).items())),
    }
