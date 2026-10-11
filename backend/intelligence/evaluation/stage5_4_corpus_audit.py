"""Descriptive, truth-free contract audit of the frozen Stage 5.4 pilot corpus."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from intelligence.evaluation.stage5_4_compare import ledger_failures
from intelligence.evaluation.stage5_4_semantic import PASS1_PROMPT, PASS2_PROMPT
from intelligence.evaluation.stage5_semantic import (
    extract_frames, frame_coverage, select_frame_timestamps, semantic_input,
)
from intelligence.ontology import techniques

SOURCES = ("01", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12")
ORIGINAL = {"01", "04", "08", "12"}


def audit(ref: str, candidate: dict, low_level: dict) -> dict:
    failures = []
    if candidate["source_ref"] != ref:
        failures.append("source reference mismatch")
    if candidate["prompts"] != {"pass1": PASS1_PROMPT, "pass2": PASS2_PROMPT}:
        failures.append("prompt drift")
    hashes = {"evidence_description": hashlib.sha256(PASS1_PROMPT.encode()).hexdigest(),
              "ontology_synthesis": hashlib.sha256(PASS2_PROMPT.encode()).hexdigest()}
    if any(row["prompt_sha256"] != hashes[row["stage"]] or not row.get("response_id")
           or not row.get("analyzer_commit") for row in candidate["model_passes"]):
        failures.append("incomplete model pass provenance")
    if candidate["content_sha256"] != hashlib.sha256(json.dumps(
            semantic_input(low_level["analysis"]), sort_keys=True).encode()).hexdigest():
        failures.append("low-level content hash mismatch")
    support_failures = ledger_failures(candidate, low_level)
    failures.extend(support_failures)
    valid_ids = set(techniques())
    findings = candidate["semantic_draft"]["findings"]
    draft = candidate["synthesis_draft"]
    events = {row["event_id"]: row for row in candidate["cta_events"]}
    duration = low_level["analysis"]["metadata"]["duration_seconds"]
    for row in findings:
        if row["technique_id"] not in valid_ids:
            failures.append("invalid ontology ID")
        if row["technique_id"].startswith("audio."):
            failures.append("unsupported source-audio label")
        end = duration if row["end_seconds"] is None else row["end_seconds"]
        if row["start_seconds"] < 0 or end > duration + .1 or end < row["start_seconds"]:
            failures.append("impossible finding timestamp")
    for row in draft["findings"]:
        if row["technique_id"].startswith("cta.") != (row["event_id"] is not None):
            failures.append("CTA event/label inconsistency")
        if row["event_id"] is not None and row["event_id"] not in events:
            failures.append("missing CTA event")
    for row in candidate["format_assessments"]:
        if not row["technique_id"].startswith("format.") or row["technique_id"] not in valid_ids:
            failures.append("invalid format assessment ID")
        if row["decision"] == "supported" and not row["positive_ledger_refs"]:
            failures.append("supported format without ledger support")
    for kind in ("findings", "structure"):
        for row in draft[kind]:
            end = duration if row["end_seconds"] is None else row["end_seconds"]
            if row["start_seconds"] < 0 or end > duration + .1 or end < row["start_seconds"]:
                failures.append("impossible synthesis timestamp")
    for row in events.values():
        if row["start_seconds"] < 0 or row["end_seconds"] > duration + .1 or row["end_seconds"] < row["start_seconds"]:
            failures.append("impossible CTA timestamp")
    for i, left in enumerate(draft["structure"]):
        for right in draft["structure"][i + 1:]:
            if left["role"] != right["role"] and min(left["end_seconds"], right["end_seconds"]) - max(
                    left["start_seconds"], right["start_seconds"]) > .05:
                failures.append("incompatible primary structure overlap")
    if candidate["frame_coverage"] != frame_coverage(candidate["selected_frames"], duration):
        failures.append("frame coverage mismatch")
    raw = json.dumps(candidate).casefold()
    if any(key in raw for key in ('"performance"', '"motion_events"', '"private_performance"')):
        failures.append("private performance or motion field present")
    if any(token in raw for token in ('data:image/', 'data:video/', '.mp4', '.mov', 'openai_api_key', 'sk-proj-')):
        failures.append("private media or credential marker present")
    return {"source_ref": ref, "status": "pass" if not failures else "fail",
            "failures": sorted(set(failures)),
            "ledger_support_failures": len(support_failures),
            "frame_coverage": candidate["frame_coverage"],
            "formats": sorted(row["technique_id"] for row in findings if row["technique_id"].startswith("format.")),
            "hooks": sorted(row["technique_id"] for row in findings if row["technique_id"].startswith("hook.")),
            "ctas": sorted(row["technique_id"] for row in findings if row["technique_id"].startswith("cta.")),
            "structure_roles": [row["role"] for row in draft["structure"]],
            "uncertainty_count": len(draft["uncertainties"]),
            "uncertainties": draft["uncertainties"],
            "cta_events": [{"interval": [row["start_seconds"], row["end_seconds"]],
                            "action": row["requested_action"],
                            "labels": candidate["cta_event_audit"]["ontology_labels_per_event"].get(row["event_id"], [])}
                           for row in candidate["cta_events"]],
            "observations": [{"time": [row["start_seconds"], row["end_seconds"]],
                              "visual": row["visible_subjects_objects"][:2] + row["visible_actions"][:2],
                              "text": row["visible_text"][:2],
                              "spoken": row["spoken_content_summary"]}
                             for row in candidate["evidence_ledger"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = {row["source_ref"]: row for row in json.loads(args.manifest.read_text())["sources"]}
    rows = []
    for ref in SOURCES:
        path = args.candidates / f"{ref}.json"
        if not path.exists():
            failure_path = args.candidates / f"{ref}.failure.json"
            failure = json.loads(failure_path.read_text()) if failure_path.exists() else {}
            low_level = json.loads((args.results / f"{ref}.json").read_text())
            content = semantic_input(low_level["analysis"])
            duration = content["metadata"]["duration_seconds"]
            frames, _ = extract_frames(Path(sources[ref]["media_path"]),
                                       select_frame_timestamps(duration, content["scenes"], content["ocr"]))
            rows.append({"source_ref": ref, "status": "rejected", "failures": [
                failure.get("error", "missing validated candidate")],
                "ledger_support_failures": None,
                "frame_coverage": frame_coverage(frames, duration),
                "formats": [], "hooks": [], "ctas": [], "structure_roles": [],
                "uncertainty_count": 0, "uncertainties": [], "cta_events": [],
                "observations": []})
            continue
        candidate = json.loads(path.read_text())
        low_level = json.loads((args.results / f"{ref}.json").read_text())
        rows.append(audit(ref, candidate, low_level))
    accepted = [row for row in rows if row["status"] == "pass"]
    distributions = {name: dict(sorted(Counter(value for row in accepted for value in row[field]).items()))
                     for name, field in (("formats", "formats"), ("hooks", "hooks"),
                                         ("ctas", "ctas"), ("structure_roles", "structure_roles"))}
    output = {"scope": "Descriptive contract audit of accepted candidates only; no human truth or accuracy estimate",
              "sources": rows, "distributions": distributions,
              "accepted_candidate_count": len(accepted),
              "videos_with_uncertainty": sum(row["uncertainty_count"] > 0 for row in accepted),
              "uncertainty_statements": sum(row["uncertainty_count"] for row in accepted),
              "ledger_support_failures": sum(row["ledger_support_failures"] for row in accepted),
              "validation_contract_failures": sum(len(row["failures"]) for row in rows)}
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    for row in rows:
        print(f"{row['source_ref']}: {row['status']}; {len(row['failures'])} failures")


if __name__ == "__main__":
    main()
