"""Offline comparison of immutable Stage 5 candidates to provisional semantic review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intelligence.evaluation.stage5_semantic import temporal_evidence_support
from intelligence.ontology import techniques
from intelligence.schemas.common import StructureRole

CATEGORIES = ("hook", "format", "editing", "text", "cta", "visual", "audio")
COVERAGE = {"complete", "partial", "unavailable"}
STATUSES = {"present", "absent", "uncertain"}
TOLERANCES = (0.25, 0.5, 1.0)


def validate_truth(truth: dict) -> None:
    if truth.get("truth_version") != "stage5.1-provisional-1":
        raise ValueError("Unknown truth version")
    if set(truth.get("category_coverage", {})) != set(CATEGORIES):
        raise ValueError("Explicit coverage is required for every category")
    if set(truth["category_coverage"].values()) - COVERAGE:
        raise ValueError("Unknown coverage")
    if truth.get("structure_coverage") not in COVERAGE:
        raise ValueError("Missing structure coverage")
    provenance = truth.get("provenance", {})
    if not all(key in provenance for key in
               ("reviewer_type", "saw_model_output_before_annotation", "blind", "adjudication_notes")):
        raise ValueError("Incomplete reviewer provenance")
    if provenance["blind"] and provenance["saw_model_output_before_annotation"]:
        raise ValueError("Contradictory blind-review provenance")
    duration = truth.get("duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("Invalid duration")
    ontology = techniques()
    for item in truth.get("items", []):
        identifier = item.get("technique_id")
        if identifier not in ontology:
            raise ValueError(f"Unsupported ontology ID: {identifier}")
        category = identifier.split(".", 1)[0]
        if item.get("coverage") not in COVERAGE or item["coverage"] != truth["category_coverage"][category]:
            raise ValueError("Item coverage disagrees with category coverage")
        _validate_item(item, duration)
    for item in truth.get("structure", []):
        if item.get("role") not in StructureRole.__args__:
            raise ValueError(f"Unsupported structure role: {item.get('role')}")
        if item.get("coverage") != truth["structure_coverage"]:
            raise ValueError("Structure coverage disagrees with item coverage")
        _validate_item(item, duration)


def _validate_item(item: dict, duration: float) -> None:
    if item.get("status") not in STATUSES:
        raise ValueError("Invalid review status")
    start, end = item.get("start_seconds"), item.get("end_seconds")
    if not isinstance(start, (int, float)) or not 0 <= start <= duration:
        raise ValueError("Invalid review start")
    if end is not None and (not isinstance(end, (int, float)) or not start < end <= duration + 0.05):
        raise ValueError("Invalid review end")
    if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
        raise ValueError("Review evidence is required")


def _overlap(a: dict, b: dict) -> float:
    ae, be = a.get("end_seconds"), b.get("end_seconds")
    if ae is None or be is None:
        return 1.0 if ae is None and be is None else 0.0
    intersection = max(0.0, min(ae, be) - max(a["start_seconds"], b["start_seconds"]))
    union = max(ae, be) - min(a["start_seconds"], b["start_seconds"])
    return intersection / union if union > 0 else 0.0


def _interval_close(a: dict, b: dict, tolerance: float) -> bool:
    ae, be = a.get("end_seconds"), b.get("end_seconds")
    return (ae is None and be is None and abs(a["start_seconds"] - b["start_seconds"]) <= tolerance) or (
        ae is not None and be is not None and
        abs(a["start_seconds"] - b["start_seconds"]) <= tolerance and abs(ae - be) <= tolerance)


def one_to_one(predictions: list[dict], reviewed: list[dict], predicate) -> list[tuple[int, int]]:
    """Deterministic maximum-cardinality bipartite assignment."""
    options = [[j for j, truth in enumerate(reviewed) if predicate(pred, truth)]
               for pred in predictions]
    right_owner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j in options[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in right_owner or augment(right_owner[j], seen):
                right_owner[j] = i
                return True
        return False

    for i in range(len(predictions)):
        augment(i, set())
    return sorted((i, j) for j, i in right_owner.items())


def _rates(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _flags(findings: list[dict], structure: list[dict]) -> dict:
    duplicates, cta_overlaps, contradictions = [], [], []
    for i, left in enumerate(findings):
        for j in range(i + 1, len(findings)):
            right = findings[j]
            iou = _overlap(left, right)
            if left["technique_id"] == right["technique_id"] and iou >= 0.7:
                duplicates.append([i, j])
            if left["technique_id"].startswith("cta.") and right["technique_id"].startswith("cta.") and iou >= 0.5:
                cta_overlaps.append([i, j])
    for i, left in enumerate(structure):
        for j in range(i + 1, len(structure)):
            right = structure[j]
            if left["role"] != right["role"] and _overlap(left, right) >= 0.5:
                contradictions.append([i, j])
    return {"duplicate_prediction_pairs": duplicates,
            "cta_same_event_pairs": cta_overlaps,
            "contradictory_structure_pairs": contradictions,
            "duplicate_prediction_count": len(duplicates),
            "contradictory_prediction_count": len(contradictions)}


def _score(predictions: list[dict], reviewed: list[dict], coverage: dict,
           *, label_key: str, tolerance: float | None = None) -> dict:
    scored_categories = {category for category, state in coverage.items() if state == "complete"}
    candidates = [(i, row) for i, row in enumerate(predictions)
                  if row[label_key].split(".", 1)[0] in scored_categories] if label_key == "technique_id" else list(enumerate(predictions))
    expected = [(i, row) for i, row in enumerate(reviewed)
                if row["status"] == "present" and row["coverage"] == "complete"]
    uncertain = [row for row in reviewed if row["status"] == "uncertain"]
    skipped = [i for i, row in candidates if any(
        row[label_key] == item[label_key] and _overlap(row, item) > 0.1 for item in uncertain)]
    candidates = [(i, row) for i, row in candidates if i not in skipped]
    if tolerance is None:
        predicate = lambda a, b: a[label_key] == b[label_key] and _overlap(a, b) >= 0.1
    else:
        predicate = lambda a, b: a[label_key] == b[label_key] and _interval_close(a, b, tolerance)
    pairs = one_to_one([row for _, row in candidates], [row for _, row in expected], predicate)
    matched_prediction = {candidates[i][0] for i, _ in pairs}
    matched_truth = {expected[j][0] for _, j in pairs}
    return {**_rates(len(pairs), len(candidates) - len(pairs), len(expected) - len(pairs)),
            "matched_pairs": [[candidates[i][0], expected[j][0]] for i, j in pairs],
            "unsupported_prediction_indices": [i for i, _ in candidates if i not in matched_prediction],
            "missed_reviewed_indices": [i for i, _ in expected if i not in matched_truth],
            "abstained_uncertain_prediction_indices": skipped,
            "scored_prediction_count": len(candidates), "scored_truth_count": len(expected)}


def compare(candidate: dict, truth: dict) -> dict:
    validate_truth(truth)
    if candidate["source_ref"] != truth["source_ref"]:
        raise ValueError("Source mismatch")
    findings = candidate["semantic_draft"]["findings"]
    structure = candidate["semantic_draft"]["structure"]
    catalog = {}
    for ref, item in candidate["cited_evidence"].items():
        kind = ref.split(":", 1)[0]
        start = item.get("timestamp_seconds", item.get("start_seconds"))
        end = item.get("timestamp_seconds", item.get("end_seconds"))
        catalog[ref] = (kind, start, end)
    evidence = []
    for kind, rows in (("finding", findings), ("structure", structure)):
        for index, row in enumerate(rows):
            support = temporal_evidence_support(type("Row", (), row), catalog)
            required = kind == "structure" or not row.get("technique_id", "").startswith("format.")
            evidence.append({"kind": kind, "index": index, **support,
                             "required": required,
                             "passes": bool(support["substantive_interval_support"]) or not required})
    flags = _flags(findings, structure)
    labels = _score(findings, truth["items"], truth["category_coverage"], label_key="technique_id")
    intervals = {str(tolerance): _score(findings, truth["items"], truth["category_coverage"],
                                        label_key="technique_id", tolerance=tolerance)
                 for tolerance in TOLERANCES}
    structure_coverage = {"structure": truth["structure_coverage"]}
    structural = _score(structure, truth["structure"], structure_coverage, label_key="role") if truth["structure_coverage"] == "complete" else None
    unsupported = set(labels["unsupported_prediction_indices"])
    unsupported.update(row["index"] for row in evidence if row["kind"] == "finding" and not row["passes"])
    return {"source_ref": truth["source_ref"], "candidate_analyzer_commit": candidate["analyzer_commit"],
            "truth_version": truth["truth_version"], "reviewer_provenance": truth["provenance"],
            "coverage": truth["category_coverage"], "structure_coverage": truth["structure_coverage"],
            "label": labels, "interval_matching": intervals, "structure_role_agreement": structural,
            "flags": flags, "evidence_interval_audit": evidence,
            "evidence_without_interval_support_count": sum(not row["passes"] for row in evidence),
            "unsupported_finding_count": len(unsupported),
            "unsupported_finding_indices": sorted(unsupported),
            "missed_reviewed_finding_count": len(labels["missed_reviewed_indices"]),
            "unscored_category_prediction_count": sum(
                truth["category_coverage"][row["technique_id"].split(".", 1)[0]] != "complete"
                for row in findings)}


def markdown(result: dict, candidate: dict, truth: dict) -> str:
    lines = [f"# Stage 5.1 review: {result['source_ref']}", "",
             "Provisional AI-assisted, non-blind review. Counts below use only categories marked complete; they are not population accuracy.", "",
             f"Candidate: `{result['candidate_analyzer_commit']}`; truth: `{result['truth_version']}`.", "",
             "## Coverage", ""]
    lines += [f"- {key}: {value}" for key, value in result["coverage"].items()]
    lines += [f"- structure: {result['structure_coverage']}", "", "## Separate comparison measures", "",
              f"- Label P/R/F1: {result['label']['precision']}, {result['label']['recall']}, {result['label']['f1']} (TP {result['label']['tp']}, FP {result['label']['fp']}, FN {result['label']['fn']})."]
    for tolerance, score in result["interval_matching"].items():
        lines.append(f"- Interval ±{tolerance}s: TP {score['tp']}, FP {score['fp']}, FN {score['fn']}; P/R/F1 {score['precision']}, {score['recall']}, {score['f1']}.")
    lines += [f"- Structure-role agreement: {result['structure_role_agreement']}.",
              f"- Duplicate prediction pairs: {result['flags']['duplicate_prediction_pairs']}.",
              f"- Same CTA event pairs (review, not automatic deletion): {result['flags']['cta_same_event_pairs']}.",
              f"- Contradictory structure pairs: {result['flags']['contradictory_structure_pairs']}.",
              f"- Unsupported findings: {result['unsupported_finding_indices']}; missed reviewed findings: {result['label']['missed_reviewed_indices']}.",
              f"- Items without substantive interval support: {result['evidence_without_interval_support_count']}.",
              "", "## Adjudication notes", ""]
    lines += [f"- {note}" for note in truth["provenance"]["adjudication_notes"]]
    lines += ["", "## Reviewed items", ""]
    lines += [f"- `{row['technique_id']}` {row['status']} {row['start_seconds']}–{row['end_seconds']}s ({row['coverage']}): {row['evidence']}"
              for row in truth["items"]]
    lines += ["", "## Reviewed structure", ""]
    lines += [f"- `{row['role']}` {row['status']} {row['start_seconds']}–{row['end_seconds']}s ({row['coverage']}): {row['evidence']}"
              for row in truth["structure"]]
    lines += ["", "## Evidence timing audit", ""]
    lines += [f"- {row['kind']} {row['index']}: interval {row['interval_support']}; context {row['context_support']}; pass {row['passes']}"
              for row in result["evidence_interval_audit"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-dir", type=Path, required=True)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sources", nargs="+", default=["01", "04", "08", "12"])
    args = parser.parse_args()
    if args.output_dir.resolve() == args.predictions_dir.resolve():
        raise ValueError("Comparison output must not overwrite Stage 5 predictions")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for ref in args.sources:
        candidate = json.loads((args.predictions_dir / f"{ref}.json").read_text())
        truth = json.loads((args.truth_dir / f"{ref}.json").read_text())
        result = compare(candidate, truth)
        (args.output_dir / f"{ref}.json").write_text(json.dumps(result, indent=2) + "\n")
        (args.output_dir / f"{ref}.md").write_text(markdown(result, candidate, truth))
        print(ref, result["label"]["tp"], result["label"]["fp"], result["label"]["fn"])


if __name__ == "__main__":
    main()
