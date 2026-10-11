"""Render the repaired scene-only sweep beside the previous provisional sweep."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TOLERANCES = ("0.1", "0.25", "0.5")
FOCUS = ("04", "07", "09")


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _cells(row: dict) -> str:
    return " | ".join(str(row[key]) for key in ("tp", "fp", "fn")) + " | " + " | ".join(
        _fmt(row[key]) for key in ("precision", "recall", "f1", "mean_matched_timing_error_seconds")
    ) + f" | {row['predicted_cuts']} |"


def enrich(previous: dict, repaired: dict) -> dict:
    result = repaired.copy()
    result["reference_status"] = (
        "Provisional Gemini-generated, user-reviewed pilot reference with Stage 3.2 "
        "scene-only replacement; not gold human truth or fully blinded independent truth"
    )
    result["stage3_2_reference_repair"] = {
        "source_refs": list(FOCUS),
        "previous_reference_cuts": {ref: previous["sources"][ref]["reference_cuts"] for ref in FOCUS},
        "repaired_reference_cuts": {ref: repaired["sources"][ref]["reference_cuts"] for ref in FOCUS},
        "source_07_ambiguous_excluded": 17,
        "annotation_source": "2026-10-11 conversation full-video annotations",
        "independence_limitation": "Annotating reviewer had previously seen detector-related material",
        "backup": "Private 11-record snapshot made before Stage 3.2 replacement",
    }
    return result


def render(previous: dict, repaired: dict) -> str:
    if previous["detector"] != repaired["detector"]:
        raise ValueError("Detector settings changed between sweeps")
    if set(previous["sources"]) != set(repaired["sources"]):
        raise ValueError("Pilot source set changed between sweeps")
    for ref in repaired["sources"]:
        if previous["sources"][ref]["source_sha256"] != repaired["sources"][ref]["source_sha256"]:
            raise ValueError(f"Pilot media changed: {ref}")
        for threshold in repaired["detector"]["thresholds"]:
            key = str(threshold)
            if (previous["sources"][ref]["thresholds"][key]["predicted_cuts"] !=
                    repaired["sources"][ref]["thresholds"][key]["predicted_cuts"]):
                raise ValueError(f"Prediction count changed: {ref}, {threshold}")
    ranking = repaired["ranked_thresholds_by_0.5s_f1"]
    lines = [
        "# V9 Stage 3.2: repaired provisional scene truth", "",
        "The original 11-video calibration references were Gemini-generated and user-reviewed. "
        "Only scene boundaries for 04, 07 and 09 were replaced from the supplied full-video "
        "annotations; 07's ambiguous graphic changes are excluded from scored truth. "
        "The annotating reviewer had previously seen detector-related material, so these "
        "labels are **not fully blinded independent ground truth**. They remain provisional, "
        "not gold human truth. No population accuracy is inferred.", "",
        "The previous 11 records were backed up before replacement. OCR, transcript, motion "
        "and metadata observations were preserved exactly. Production scene detection was "
        "not changed; this reran only normalization and scene detection.", "",
        f"Detector: `{repaired['detector']['class']}`, PySceneDetect "
        f"`{repaired['detector']['version']}`; `scenedetect.detect` with ContentDetector "
        "thresholds 20, 24, 27, 30, 33, 36, 40 and 45. All other settings are fixed and "
        "recorded in the JSON. Threshold 27 remains the production baseline.", "",
        "## Reference changes", "",
        "| Source | Previous boundaries | Repaired boundaries | Excluded ambiguous |",
        "| --- | ---: | ---: | ---: |",
    ]
    for ref in FOCUS:
        old, new = previous["sources"][ref], repaired["sources"][ref]
        lines.append(f"| {ref} | {old['reference_cuts']} | {new['reference_cuts']} | "
                     f"{17 if ref == '07' else 0} |")
    lines.extend(["", "## Threshold 27 before and after reference repair", "",
                  "The predicted cuts are identical in both runs; only the reference changed.", "",
                  "| Tolerance | Reference | TP | FP | FN | P | R | F1 | Mean error (s) | Cuts |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for tolerance in TOLERANCES:
        for label, report in (("Previous", previous), ("Repaired", repaired)):
            row = report["aggregate"]["27"][tolerance]
            lines.append(f"| ±{tolerance} s | {label} | {_cells(row)}")
    lines.extend(["", "## Sources 04, 07 and 09 at threshold 27", "",
                  "| Source | Tolerance | Reference | TP | FP | FN | P | R | F1 | Mean error (s) | Cuts |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for ref in FOCUS:
        for tolerance in TOLERANCES:
            for label, report in (("Previous", previous), ("Repaired", repaired)):
                result = report["sources"][ref]["thresholds"]["27"]
                row = result["scores"][tolerance].copy()
                row["predicted_cuts"] = result["predicted_cuts"]
                row["mean_matched_timing_error_seconds"] = (
                    sum(row["timing_errors_seconds"]) / len(row["timing_errors_seconds"])
                    if row["timing_errors_seconds"] else None)
                lines.append(f"| {ref} | ±{tolerance} s | {label} | {_cells(row)}")
    lines.extend(["", "## Repaired aggregate by threshold", "",
                  "Thresholds are ordered by ±0.5 s F1. Greater precision at a higher threshold "
                  "comes with lower recall; no production threshold is selected."])
    for tolerance in TOLERANCES:
        lines.extend(["", f"### ±{tolerance} s", "",
                      "| Threshold | TP | FP | FN | P | R | F1 | Mean error (s) | Cuts |",
                      "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for threshold in ranking:
            row = repaired["aggregate"][str(threshold)][tolerance]
            lines.append(f"| {threshold}{' (baseline)' if threshold == 27 else ''} | {_cells(row)}")
    lines.extend(["", "## Per-video results", "",
                  "Each cell is `TP / FP / FN; P / R / F1; predicted cuts; mean matched error (s)`. "
                  "Undefined values are shown as —. The JSON contains unmatched timestamps."])
    for tolerance in TOLERANCES:
        lines.extend(["", f"### ±{tolerance} s", "",
                      "| Video | Truth | " + " | ".join(str(t) for t in ranking) + " |",
                      "| --- | ---: | " + " | ".join("---" for _ in ranking) + " |"])
        for ref, source in repaired["sources"].items():
            cells = []
            for threshold in ranking:
                result = source["thresholds"][str(threshold)]
                row = result["scores"][tolerance]
                errors = row["timing_errors_seconds"]
                error = sum(errors) / len(errors) if errors else None
                cells.append(f"{row['tp']}/{row['fp']}/{row['fn']}; "
                             f"{_fmt(row['precision'])}/{_fmt(row['recall'])}/{_fmt(row['f1'])}; "
                             f"{result['predicted_cuts']}; {_fmt(error)}")
            lines.append(f"| **{ref}** | {source['reference_cuts']} | " + " | ".join(cells) + " |")
    leader = ranking[0]
    leading = repaired["aggregate"][str(leader)]["0.5"]
    baseline = repaired["aggregate"]["27"]["0.5"]
    lines.extend(["", "## Interpretation", "",
                  f"Threshold {leader} ranks first at ±0.5 s F1 ({_fmt(leading['f1'])} "
                  f"versus {_fmt(baseline['f1'])} at 27). It removes "
                  f"{baseline['fp'] - leading['fp']} false positives but also loses "
                  f"{baseline['tp'] - leading['tp']} true matches at this tolerance. "
                  "This small F1 difference does not justify an automatic production change.", "",
                  "The large gain after repair shows that the earlier provisional reference "
                  "omitted many visually annotated boundaries in 04 and 07. At 09, four of "
                  "five threshold-27 predictions match the newly included synthetic beats; "
                  "one remains unmatched. This comparison cannot establish the exact fraction "
                  "of detector error versus reference error because the replacement annotation "
                  "was not fully blinded. The 04 and 07 times were mostly located from 0.25 s "
                  "sampling, limiting interpretation at ±0.1 s. No OCR, semantic labels, "
                  "transcription, motion, or full analysis pipeline was used.", "",
                  "## Local inputs", "",
                  "The previous private truth snapshot is at "
                  "`/private/tmp/cm-v9-pilot/provisional-reviewed-before-stage3-2`; the repaired "
                  "records are at `/private/tmp/cm-v9-pilot/provisional-reviewed`. The committed "
                  "scene-only annotation file and `stage3_2_scene_truth` script reproduce the "
                  "replacement. Run `stage3_scene` against the repaired private truth and the "
                  "same pilot manifest and baseline results, then `stage3_2_report` against the "
                  "previous and repaired sweep JSON files to reproduce these tables. "
                  "A separate full-record validation found a pre-existing source 08 OCR interval "
                  "past its manifest duration; it is unchanged and outside this scene-only run.", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--repaired", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    previous, repaired = json.loads(args.previous.read_text()), json.loads(args.repaired.read_text())
    markdown = render(previous, repaired)
    args.json.write_text(json.dumps(enrich(previous, repaired), indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(markdown)


if __name__ == "__main__":
    main()
