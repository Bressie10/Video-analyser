"""Evaluate Stage 5, 5.2, and 5.3 only after four-video inference completes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intelligence.evaluation.stage5_1_review import compare
from intelligence.evaluation.stage5_3_semantic import (
    ChunkDescription, LedgerObservation, SynthesisDraft, cta_event_audit,
    validate_chunk, validate_synthesis,
)
from intelligence.evaluation.stage5_semantic import evidence_catalog, semantic_input

SOURCES = ("01", "04", "08", "12")


def ledger_failures(candidate: dict, low_level: dict) -> list[str]:
    """Independent reconstruction of each ledger and synthesis support gate."""
    content = semantic_input(low_level["analysis"])
    frames = candidate["selected_frames"]
    catalog = evidence_catalog(content, frames)
    by_chunk = {}
    for item in candidate["evidence_ledger"]:
        by_chunk.setdefault(item["chunk_id"], []).append(item)
    failures = []
    for chunk in candidate["chunk_plan"]:
        observations = [LedgerObservation.model_validate({
            key: value for key, value in item.items() if key not in ("ledger_id", "chunk_id")})
            for item in by_chunk.get(chunk["chunk_id"], [])]
        described = ChunkDescription(chunk_start_seconds=chunk["start_seconds"],
                                     chunk_end_seconds=chunk["end_seconds"],
                                     observations=observations, uncertainties=[])
        try:
            recovered = validate_chunk(described, chunk, catalog)
            if [item["ledger_id"] for item in recovered] != [
                    item["ledger_id"] for item in by_chunk.get(chunk["chunk_id"], [])]:
                failures.append(f"{chunk['chunk_id']}: ledger IDs changed")
        except (ValueError, TypeError) as exc:
            failures.append(f"{chunk['chunk_id']}: {exc}")
    try:
        validate_synthesis(SynthesisDraft.model_validate(candidate["synthesis_draft"]),
                           candidate["evidence_ledger"], content, frames)
    except (ValueError, TypeError) as exc:
        failures.append(f"synthesis: {exc}")
    return failures


def compact(candidate: dict, result: dict) -> dict:
    findings = candidate["semantic_draft"]["findings"]
    output = {"analyzer_commit": candidate["analyzer_commit"],
              "model": candidate["model_reported"], "response_id": candidate.get("response_id"),
              "prompt_sha256": candidate["prompt_sha256"],
              "frame_coverage": candidate.get("frame_coverage"),
              "label": result["label"], "interval_matching": result["interval_matching"],
              "structure_role_agreement": result["structure_role_agreement"],
              "missed_reviewed_finding_count": result["missed_reviewed_finding_count"],
              "missed_reviewed_indices": result["label"]["missed_reviewed_indices"],
              "unsupported_finding_count": result["unsupported_finding_count"],
              "unsupported_finding_indices": result["unsupported_finding_indices"],
              "contradictory_structure_pairs": result["flags"]["contradictory_structure_pairs"],
              "structure_covered_runtime_fraction": result["structure_covered_runtime_fraction"],
              "whole_video_formats": sorted(row["technique_id"] for row in findings
                                            if row["technique_id"].startswith("format.")),
              "overlapping_cta_pair_count": len(result["flags"]["cta_same_event_pairs"]),
              "evidence_interval_support_failure_count": result["evidence_without_interval_support_count"]}
    if "cta_event_audit" in candidate:
        output["cta_event_audit"] = candidate["cta_event_audit"]
        output["model_passes"] = candidate["model_passes"]
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage5-dir", type=Path, required=True)
    parser.add_argument("--stage5-2-dir", type=Path, required=True)
    parser.add_argument("--stage5-3-dir", type=Path, required=True)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    missing = [str(args.stage5_3_dir / f"{ref}.json") for ref in SOURCES
               if not (args.stage5_3_dir / f"{ref}.json").is_file()]
    if missing:
        raise ValueError(f"All four Stage 5.3 inferences must finish before truth is read: {missing}")
    rows = []
    for ref in SOURCES:
        candidates = {
            "stage5": json.loads((args.stage5_dir / f"{ref}.json").read_text()),
            "stage5_2": json.loads((args.stage5_2_dir / f"{ref}.json").read_text()),
            "stage5_3": json.loads((args.stage5_3_dir / f"{ref}.json").read_text()),
        }
        truth = json.loads((args.truth_dir / f"{ref}.json").read_text())
        results = {name: compact(candidate, compare(candidate, truth))
                   for name, candidate in candidates.items()}
        results["stage5_3"]["evidence_ledger_support_failures"] = ledger_failures(
            candidates["stage5_3"], json.loads((args.results / f"{ref}.json").read_text()))
        rows.append({"source_ref": ref, "truth_version": truth["truth_version"],
                     "truth_provenance": truth["provenance"], **results})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"comparison_version": "stage5.3-1",
        "scoring_scope": "Provisional complete categories only; partial and unavailable abstain",
        "sources": rows}, indent=2) + "\n")
    for row in rows:
        print(row["source_ref"], *(f"{name} {row[name]['label']['tp']}/"
              f"{row[name]['label']['fp']}/{row[name]['label']['fn']}"
              for name in ("stage5", "stage5_2", "stage5_3")))


if __name__ == "__main__":
    main()
