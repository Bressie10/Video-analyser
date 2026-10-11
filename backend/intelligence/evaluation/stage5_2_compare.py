"""Compare Stage 5 and Stage 5.2 candidates after inference, using provisional truth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from intelligence.evaluation.stage5_1_review import compare
from intelligence.evaluation.stage5_semantic import frame_coverage


def compact(candidate: dict, result: dict, duration: float) -> dict:
    return {"model": candidate["model_reported"],
            "analyzer_commit": candidate["analyzer_commit"],
            "response_id": candidate.get("response_id"),
            "prompt_sha256": candidate["prompt_sha256"],
            "frame_coverage": candidate.get("frame_coverage") or frame_coverage(
                candidate["selected_frames"], duration),
            "label": result["label"], "interval_matching": result["interval_matching"],
            "structure_role_agreement": result["structure_role_agreement"],
            "structure_covered_runtime_fraction": result["structure_covered_runtime_fraction"],
            "duplicate_prediction_count": result["flags"]["duplicate_prediction_count"],
            "overlapping_cta_pair_count": len(result["flags"]["cta_same_event_pairs"]),
            "contradictory_structure_count": result["flags"]["contradictory_prediction_count"],
            "evidence_interval_support_failure_count": result["evidence_without_interval_support_count"],
            "unsupported_finding_count": result["unsupported_finding_count"],
            "missed_reviewed_finding_count": result["missed_reviewed_finding_count"],
            "unscored_category_prediction_count": result["unscored_category_prediction_count"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", nargs="+", default=["01", "04", "08", "12"])
    args = parser.parse_args()
    rows = []
    for ref in args.sources:
        baseline = json.loads((args.baseline_dir / f"{ref}.json").read_text())
        candidate = json.loads((args.candidate_dir / f"{ref}.json").read_text())
        truth = json.loads((args.truth_dir / f"{ref}.json").read_text())
        rows.append({"source_ref": ref, "truth_version": truth["truth_version"],
                     "truth_provenance": truth["provenance"],
                     "baseline": compact(baseline, compare(baseline, truth), truth["duration_seconds"]),
                     "stage5_2": compact(candidate, compare(candidate, truth), truth["duration_seconds"])})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"comparison_version": "stage5.2-1",
                                       "scoring_scope": "Complete provisional categories only; partial and unavailable abstain",
                                       "sources": rows}, indent=2) + "\n")
    for row in rows:
        old, new = row["baseline"], row["stage5_2"]
        print(row["source_ref"],
              f"frames {old['frame_coverage']['selected_frame_count']}->{new['frame_coverage']['selected_frame_count']}",
              f"gap {old['frame_coverage']['largest_frame_gap_seconds']}->{new['frame_coverage']['largest_frame_gap_seconds']}",
              f"label TP/FP/FN {old['label']['tp']}/{old['label']['fp']}/{old['label']['fn']}"
              f"->{new['label']['tp']}/{new['label']['fp']}/{new['label']['fn']}")


if __name__ == "__main__":
    main()
