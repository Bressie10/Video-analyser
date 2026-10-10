"""Validate and summarize the private V9 Stage 3.1 visual scene audit."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

REFS = ("04", "07", "09")
CATEGORIES = {"editorial_cut", "editorial_transition", "animated_graphic_layout",
              "cgi_or_synthetic_animation", "object_or_subject_motion"}
STATUSES = {"likely", "possible", "none"}
OFFSETS = (-0.25, -0.05, 0.05, 0.25)


def validate(audit: dict, sweep: dict) -> None:
    """Require a single inspected decision for every specified unmatched cut."""
    if audit.get("schema_version") != 1 or audit.get("baseline_threshold") != 27 or \
            audit.get("matching_tolerance_seconds") != 0.5:
        raise ValueError("Unexpected Stage 3.1 audit configuration")
    if audit.get("detector") != sweep.get("detector") or audit.get("source_sha256_by_ref") != {
            ref: sweep["sources"][ref]["source_sha256"] for ref in REFS}:
        raise ValueError("Audit detector or source identity mismatch")
    expected = {(ref, index, timestamp)
                for ref in REFS
                for index, timestamp in enumerate(
                    sweep["sources"][ref]["thresholds"]["27"]["scores"]["0.5"]
                    ["unmatched_prediction_seconds"], 1)}
    actual = set()
    for event in audit["events"]:
        key = (event["source_ref"], event["prediction_index"], event["timestamp_seconds"])
        if key in actual or key not in expected:
            raise ValueError(f"Duplicate or unexpected inspected cut: {key}")
        actual.add(key)
        if event["category"] not in CATEGORIES or event["truth_review_status"] not in STATUSES:
            raise ValueError(f"Unrecognized visual decision: {key}")
        if not isinstance(event["observation"], str) or not event["observation"].strip():
            raise ValueError(f"Missing visual observation: {key}")
        difference = event["mean_absolute_pixel_difference_minus_0_05_to_plus_0_05"]
        if not isinstance(difference, (int, float)) or not math.isfinite(difference) or difference < 0:
            raise ValueError(f"Invalid frame difference: {key}")
        samples = event["sample_timestamps_seconds"]
        files = event["private_frame_files"]
        if set(samples) != {f"{offset:+.2f}" for offset in OFFSETS} or set(files) != set(samples):
            raise ValueError(f"Four frame samples required: {key}")
        for offset in OFFSETS:
            label = f"{offset:+.2f}"
            if abs(samples[label] - round(key[2] + offset, 3)) > 0.001 or \
                    files[label] != f"{key[0]}/{key[1]:03d}_{label}.jpg":
                raise ValueError(f"Frame sample mismatch: {key}")
    if actual != expected:
        raise ValueError(f"Missing inspected cuts: {sorted(expected - actual)}")
    category_counts = {ref: dict(Counter(event["category"] for event in audit["events"]
                                         if event["source_ref"] == ref)) for ref in REFS}
    category_counts["all"] = dict(Counter(event["category"] for event in audit["events"]))
    status_counts = dict(Counter(event["truth_review_status"] for event in audit["events"]))
    if audit["summary"] != {"by_category": category_counts,
                            "truth_review_status": status_counts,
                            "inspected_events": len(expected)}:
        raise ValueError("Audit summary differs from event decisions")
    for status in ("likely", "possible"):
        rows = [{"source_ref": event["source_ref"],
                 "timestamp_seconds": event["timestamp_seconds"]}
                for event in audit["events"] if event["truth_review_status"] == status]
        if audit["suspected_truth_errors"][status] != rows:
            raise ValueError(f"Suspected truth error list differs: {status}")


def markdown(audit: dict) -> str:
    count = audit["summary"]["by_category"]
    labels = {"editorial_cut": "Likely editorial cut missing from reference",
              "editorial_transition": "Likely editorial transition missing from reference",
              "animated_graphic_layout": "Animated graphic or split-screen layout",
              "cgi_or_synthetic_animation": "CGI or synthetic crowd change",
              "object_or_subject_motion": "Object or subject motion within a shot"}
    lines = ["# V9 Stage 3.1 scene false-positive audit", "",
             "Threshold 27; ±0.5 s one-to-one matching from the Stage 3 sweep. "
             "The reference remains provisional Gemini + human-checked calibration truth. "
             "This is a visual audit of 102 unmatched predictions in videos 04, 07 and 09, "
             "not an estimate of population detector accuracy.", "",
             "Four decoded frames were inspected around each timestamp at approximately "
             "−0.25, −0.05, +0.05 and +0.25 s. Denser frame sequences were inspected for "
             "ambiguous events. A simple mean absolute pixel difference between the inner "
             "frames is recorded in JSON as context, not as a semantic classifier. "
             "Private frame evidence was kept outside Git because media rights are not "
             "independently verified.", "",
             "## Observed categories", "",
             "| Category | 04 | 07 | 09 | Total |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for category, label in labels.items():
        lines.append(f"| {label} | {count['04'].get(category, 0)} | "
                     f"{count['07'].get(category, 0)} | {count['09'].get(category, 0)} | "
                     f"{count['all'].get(category, 0)} |")
    status = audit["summary"]["truth_review_status"]
    lines.extend(["", f"**Reference review:** {status.get('likely', 0)} likely omitted "
                  f"boundaries; {status.get('possible', 0)} possible boundary questions; "
                  f"{status.get('none', 0)} events without a clear editorial boundary.", "",
                  "## Timestamp examples", "",
                  "- **04 2.542 s:** roadside approach changes abruptly to a closer view; "
                  "likely omitted cut. At 49.333 s, foam crosses the face within a continuous "
                  "shot, a plausible detector false positive.",
                  "- **07 35.100 s:** workshop changes to helmet close-up; likely omitted "
                  "cut. At 14.933 s, a blue text panel slides in; graphic boundary status "
                  "needs adjudication.",
                  "- **09 2.200, 6.100, 10.200 and 14.067 s:** synthetic crowd and "
                  "camera scale change abruptly; these could be edited CGI beat boundaries. "
                  "At 15.000 s, frame-by-frame inspection showed only subtle crowd movement "
                  "with no clear new composition.", "",
                  "## Suspected truth errors", "",
                  "Likely omitted editorial boundaries (reannotation candidates):", ""])
    for ref in REFS:
        times = [row["timestamp_seconds"] for row in audit["suspected_truth_errors"]["likely"]
                 if row["source_ref"] == ref]
        if times:
            lines.append(f"- **{ref} ({len(times)}):** " + ", ".join(f"{value:.3f}" for value in times) + " s")
    lines.extend(["", "Possible boundary questions requiring adjudication:", ""])
    for ref in REFS:
        times = [row["timestamp_seconds"] for row in audit["suspected_truth_errors"]["possible"]
                 if row["source_ref"] == ref]
        if times:
            lines.append(f"- **{ref} ({len(times)}):** " + ", ".join(f"{value:.3f}" for value in times) + " s")
    lines.extend(["", "The 86 likely omissions mean the current provisional reference "
                  "cannot reliably assign all unmatched detections to detector error. "
                  "The CGI and graphic boundaries require an explicit annotation rule before "
                  "being treated as either true cuts or false positives. No production detector "
                  "change is proposed from this audit.", "",
                  "## Reproduce frame samples", "",
                  "From `backend`, run `python -m intelligence.evaluation.stage3_1_frames "
                  "--manifest PRIVATE_MANIFEST --sweep intelligence/evaluation/stage3/scene_threshold_sweep.json "
                  "--out PRIVATE_OUTPUT_DIR`. The command verifies source hashes, normalises "
                  "each selected video once, and extracts the four sampled frames per unmatched "
                  "prediction. It does not run scene detection or any other analysis signal. "
                  "OpenCV seeks to approximate decoded frame times.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--sweep", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    audit = json.loads(args.audit.read_text())
    validate(audit, json.loads(args.sweep.read_text()))
    args.markdown.write_text(markdown(audit))


if __name__ == "__main__":
    main()
