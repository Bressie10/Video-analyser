"""Private, offline V9 Stage 1 low-level truth review and agreement.

This is a pilot file format, not a frozen V8.5 or production contract.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from .v8_baseline import _edit_distance, _interval, _iou, _tokens


LOW_LEVEL_TRUTH_VERSION = "1.0.0"
SIGNALS = ("scene_boundaries", "ocr", "transcript", "motion", "metadata")
MOTION_TYPES = {"camera_shake", "camera_zoom", "camera_pan", "general_motion",
                "local_motion", "unknown"}
METADATA_FIELDS = {"duration_seconds", "video.resolution.width", "video.resolution.height", "video.fps"}


def _identity(record: dict, kind: str) -> str:
    key = "annotator_ref" if kind == "independent" else "reviewer_ref"
    timestamp_key = "annotated_at" if kind == "independent" else "reviewed_at"
    other_key = "reviewer_ref" if kind == "independent" else "annotator_ref"
    other_timestamp = "reviewed_at" if kind == "independent" else "annotated_at"
    if other_key in record or other_timestamp in record:
        raise ValueError(f"{kind} record has conflicting author provenance")
    author = record.get(key)
    if not isinstance(author, str) or not author.strip():
        raise ValueError(f"{kind} record needs nonblank {key}")
    timestamp = record.get(timestamp_key)
    if not isinstance(timestamp, str):
        raise ValueError(f"{kind} record needs {timestamp_key}")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Invalid {timestamp_key}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{timestamp_key} must be timezone-aware")
    return author


def validate_record(record: dict, duration_seconds: float | None = None,
                    *, kind: str | None = None) -> str:
    """Validate provenance, coverage, and observations without reading V8 output."""
    if not isinstance(record, dict) or record.get("low_level_truth_version") != LOW_LEVEL_TRUTH_VERSION:
        raise ValueError("Unsupported low-level truth version")
    if not isinstance(record.get("source_ref"), str) or not record["source_ref"].strip():
        raise ValueError("Low-level truth needs source_ref")
    actual_kind = record.get("record_kind")
    if actual_kind not in {"independent", "reviewed"} or (kind is not None and actual_kind != kind):
        raise ValueError(f"Expected {kind or 'independent/reviewed'} low-level truth record")
    allowed = {"low_level_truth_version", "source_ref", "record_kind", "coverage", "notes", "observations"}
    allowed |= ({"annotator_ref", "annotated_at"} if actual_kind == "independent"
                else {"reviewer_ref", "reviewed_at"})
    if set(record) - allowed:
        raise ValueError("Unexpected low-level truth fields; detector output is not annotation truth")
    author = _identity(record, actual_kind)
    if record.get("notes") is not None and not isinstance(record["notes"], str):
        raise ValueError("Low-level notes must be a string or null")
    coverage, observations = record.get("coverage"), record.get("observations")
    if not isinstance(coverage, dict) or set(coverage) != set(SIGNALS):
        raise ValueError("Every low-level signal needs explicit coverage")
    if not isinstance(observations, dict) or not set(observations) <= set(SIGNALS):
        raise ValueError("Observations must be a signal-keyed object")
    for signal, status in coverage.items():
        if status not in {"complete", "partial", "unavailable"}:
            raise ValueError(f"Invalid low-level coverage: {signal}")
        if status == "complete" and signal not in observations:
            raise ValueError(f"Complete truth section missing: {signal}")
    if coverage["scene_boundaries"] == "complete":
        times = [row["time_seconds"] for row in observations["scene_boundaries"]]
        if any(not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 < t or
               (duration_seconds is not None and t >= duration_seconds) for t in times):
            raise ValueError("Editorial boundaries must be within the source duration")
        if times != sorted(set(times)):
            raise ValueError("Editorial boundaries must be unique and in time order")
    for signal, start, end in (("ocr", "start_seconds", "end_seconds"),
                               ("motion", "start_seconds", "end_seconds")):
        if coverage[signal] != "complete":
            continue
        for row in observations[signal]:
            a, b = _interval(row, start, end)
            if not math.isfinite(a) or not math.isfinite(b) or (duration_seconds is not None and b > duration_seconds):
                raise ValueError(f"{signal} interval exceeds source duration")
            if signal == "ocr" and (not row.get("text") or not row.get("normalized_text")):
                raise ValueError("Visible OCR text needs literal and normalized text")
            if signal == "motion" and row["type"] not in MOTION_TYPES:
                raise ValueError("Motion truth must map to a V8 output type")
    if coverage["transcript"] == "complete":
        transcript = observations["transcript"]
        if not isinstance(transcript.get("text"), str):
            raise ValueError("Human transcript text is required")
        for segment in transcript.get("segments", []):
            a, b = _interval(segment, "start", "end")
            if not math.isfinite(a) or not math.isfinite(b) or (duration_seconds is not None and b > duration_seconds):
                raise ValueError("Transcript segment exceeds source duration")
    if coverage["metadata"] == "complete":
        if "duration_seconds" not in observations["metadata"]:
            raise ValueError("Complete metadata truth needs independent duration_seconds")
        for field, row in observations["metadata"].items():
            if field not in METADATA_FIELDS:
                raise ValueError(f"Unsupported independent metadata field: {field}")
            value, tolerance = row.get("value"), row.get("tolerance", 0)
            if (not isinstance(value, (int, float)) or not math.isfinite(value) or
                    not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0):
                raise ValueError(f"Invalid metadata truth: {field}")
    return author


def _pair(candidates, n_left: int, n_right: int) -> list[tuple[int, int]]:
    """Deterministic maximum-cardinality matching with quality-ordered edges."""
    edges = [[] for _ in range(n_left)]
    for quality, left, right in sorted(candidates, key=lambda row: (-row[0], row[1], row[2])):
        edges[left].append(right)
    owner = {}

    def assign(left, seen):
        for right in edges[left]:
            if right in seen:
                continue
            seen.add(right)
            if right not in owner or assign(owner[right], seen):
                owner[right] = left
                return True
        return False

    for left in range(n_left):
        assign(left, set())
    return sorted((left, right) for right, left in owner.items())


def _interval_agreement(left, right, start, end, min_iou):
    a = [_interval(row, start, end) for row in left]
    b = [_interval(row, start, end) for row in right]
    pairs = _pair([(_iou(first, second), i, j) for i, first in enumerate(a)
                   for j, second in enumerate(b) if _iou(first, second) >= min_iou], len(a), len(b))
    return {"matched": [{"left_index": i, "right_index": j, "temporal_iou": _iou(a[i], b[j])}
                        for i, j in pairs],
            "unmatched_left_indices": [i for i in range(len(a)) if i not in {p for p, _ in pairs}],
            "unmatched_right_indices": [j for j in range(len(b)) if j not in {q for _, q in pairs}]}


def compare_records(left: dict, right: dict, *, scene_tolerance=0.25, min_iou=0.5) -> dict:
    """Report low-level human agreement by signal, without a universal score."""
    if not math.isfinite(scene_tolerance) or scene_tolerance < 0 or not 0 < min_iou <= 1:
        raise ValueError("Invalid agreement tolerance")
    a, b = validate_record(left, kind="independent"), validate_record(right, kind="independent")
    if left["source_ref"] != right["source_ref"] or a == b:
        raise ValueError("Agreement requires one source and distinct annotators")
    result = {"source_ref": left["source_ref"], "annotators": [a, b], "signals": {}}
    for signal in SIGNALS:
        statuses = [left["coverage"][signal], right["coverage"][signal]]
        if statuses != ["complete", "complete"]:
            result["signals"][signal] = {"status": "not_compared", "coverage": statuses}
            continue
        x, y = left["observations"][signal], right["observations"][signal]
        if signal == "scene_boundaries":
            first, second = [row["time_seconds"] for row in x], [row["time_seconds"] for row in y]
            pairs = _pair([(1 / (1 + abs(t - u)), i, j) for i, t in enumerate(first)
                           for j, u in enumerate(second) if abs(t - u) <= scene_tolerance], len(first), len(second))
            row = {"tolerance_seconds": scene_tolerance,
                   "matched": [{"left_index": i, "right_index": j,
                                "left_seconds": first[i], "right_seconds": second[j],
                                "absolute_timing_difference_seconds": abs(first[i] - second[j])}
                               for i, j in pairs],
                   "unmatched_left_seconds": [t for i, t in enumerate(first) if i not in {p for p, _ in pairs}],
                   "unmatched_right_seconds": [t for j, t in enumerate(second) if j not in {q for _, q in pairs}]}
        elif signal == "ocr":
            row = _interval_agreement(x, y, "start_seconds", "end_seconds", min_iou)
            for match in row["matched"]:
                i, j = match["left_index"], match["right_index"]
                match["normalized_text_agrees"] = _tokens(x[i]["normalized_text"]) == _tokens(y[j]["normalized_text"])
                match["left_normalized_text"] = x[i]["normalized_text"]
                match["right_normalized_text"] = y[j]["normalized_text"]
        elif signal == "transcript":
            first, second = _tokens(x["text"]), _tokens(y["text"])
            row = {"text_agrees": first == second, "token_edit_distance": _edit_distance(first, second),
                   "left_tokens": len(first), "right_tokens": len(second)}
            if "segments" in x and "segments" in y:
                row["segment_timing"] = _interval_agreement(x["segments"], y["segments"], "start", "end", min_iou)
                for match in row["segment_timing"]["matched"]:
                    i, j = match["left_index"], match["right_index"]
                    match["start_difference_seconds"] = abs(x["segments"][i]["start"] - y["segments"][j]["start"])
                    match["end_difference_seconds"] = abs(x["segments"][i]["end"] - y["segments"][j]["end"])
            else:
                row["segment_timing"] = None
        elif signal == "motion":
            row = _interval_agreement(x, y, "start_seconds", "end_seconds", min_iou)
            for match in row["matched"]:
                i, j = match["left_index"], match["right_index"]
                match["type_agrees"] = x[i]["type"] == y[j]["type"]
                match["left_type"] = x[i]["type"]
                match["right_type"] = y[j]["type"]
        else:
            row = {}
            for field in sorted(set(x) | set(y)):
                if field not in x or field not in y:
                    row[field] = {"status": "missing_from_one_pass"}
                    continue
                first, second = x[field], y[field]
                tolerance = max(first.get("tolerance", 0), second.get("tolerance", 0))
                row[field] = {"left_value": first["value"], "right_value": second["value"],
                              "left_tolerance": first.get("tolerance", 0),
                              "right_tolerance": second.get("tolerance", 0),
                              "absolute_difference": abs(first["value"] - second["value"]),
                              "within_declared_tolerance": abs(first["value"] - second["value"]) <= tolerance}
        result["signals"][signal] = {"status": "compared", "result": row}
    return result


def audit(manifest: dict, low_level_dir: Path, *, scene_tolerance=0.25, min_iou=0.5) -> tuple[dict, dict]:
    """Check independent files and reviewed provenance; return only reviewed records for scoring."""
    expected = {item["source_ref"]: item for item in manifest["sources"]}
    annotations_dir, reviewed_dir = low_level_dir / "annotations", low_level_dir / "reviewed"
    by_source = {ref: [] for ref in expected}
    for path in sorted(annotations_dir.glob("*.json")):
        record = json.loads(path.read_text())
        ref = record.get("source_ref")
        if ref not in expected:
            raise ValueError(f"Unknown low-level annotation source: {ref}")
        validate_record(record, expected[ref]["duration_seconds"], kind="independent")
        by_source[ref].append(record)
    report, reviewed_records = {}, {}
    for ref, item in expected.items():
        records = by_source[ref]
        reviewed_path, notes_path = reviewed_dir / f"{ref}.json", reviewed_dir / f"{ref}.md"
        if len(records) > 2:
            raise ValueError(f"Exactly two independent low-level annotators allowed: {ref}")
        if len({r["annotator_ref"] for r in records}) != len(records):
            raise ValueError(f"Same low-level annotator cannot count twice: {ref}")
        if reviewed_path.exists() or item["low_level_truth_available"]:
            if len(records) != 2:
                raise ValueError(f"Two independent low-level annotators required: {ref}")
            if not reviewed_path.exists():
                raise ValueError(f"Reviewed low-level truth missing: {ref}")
            reviewed = json.loads(reviewed_path.read_text())
            reviewer = validate_record(reviewed, item["duration_seconds"], kind="reviewed")
            if reviewed["source_ref"] != ref or reviewer in {r["annotator_ref"] for r in records}:
                raise ValueError(f"Reviewed low-level truth needs same source and separate reviewer: {ref}")
            review_time = datetime.fromisoformat(reviewed["reviewed_at"].replace("Z", "+00:00"))
            annotation_times = [datetime.fromisoformat(r["annotated_at"].replace("Z", "+00:00"))
                                for r in records]
            if review_time < max(annotation_times):
                raise ValueError(f"Reviewed low-level truth predates an independent annotation: {ref}")
            if not notes_path.exists() or not notes_path.read_text().strip():
                raise ValueError(f"Low-level adjudication notes required: {ref}")
            if not item["low_level_truth_available"]:
                raise ValueError(f"Reviewed low-level truth exists but manifest says unavailable: {ref}")
            reviewed_records[ref] = reviewed
        agreement = (compare_records(records[0], records[1], scene_tolerance=scene_tolerance, min_iou=min_iou)
                     if len(records) == 2 else None)
        report[ref] = {"independent_annotators": sorted(r["annotator_ref"] for r in records),
                       "reviewed": ref in reviewed_records, "agreement": agreement}
    for path in reviewed_dir.glob("*.json"):
        if path.stem not in expected:
            raise ValueError(f"Unknown reviewed low-level source: {path.stem}")
    return {"sources": report, "reviewed_sources": sorted(reviewed_records)}, reviewed_records
