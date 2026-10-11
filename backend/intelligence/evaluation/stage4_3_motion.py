"""Offline V9 Stage 4.3 motion evidence experiment; production is untouched."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
from pathlib import Path

from app import video_processing as motion
from .stage4_motion import _interval_stats, metrics, runs_to_events
from .stage4_2_motion import overlaps, suppress_preserving_scene_gaps

VARIANTS = (
    "existing_semantic_output",
    "nonoverlap_plus_singleton",
    "scene_aware_plus_singleton",
    "simplified_cut_mask_plus_singleton",
    "simplified_scene_reset_plus_singleton",
)
VALID = {"camera_pan", "camera_zoom", "camera_shake", "local_subject_motion", "general_scene_motion"}
DESCRIPTORS = ("mean_flow_magnitude", "active_pixel_coverage", "median_global_vector_magnitude",
               "coherence", "radial_alignment")


def flow_descriptors(flow) -> dict:
    """Measure the same active-flow quantities used by the unchanged classifier."""
    import numpy as np

    magnitudes = np.linalg.norm(flow, axis=2)
    active = magnitudes >= motion.MOTION_MAGNITUDE_THRESHOLD
    result = {"mean_flow_magnitude": float(np.mean(magnitudes)),
              "active_pixel_coverage": float(np.mean(active)),
              "median_global_vector_magnitude": None, "coherence": None,
              "radial_alignment": None}
    if not np.any(active):
        return result
    vectors = flow[active]
    mean_active = float(np.mean(magnitudes[active]))
    median_magnitude = float(np.linalg.norm(np.median(vectors, axis=0)))
    height, width = magnitudes.shape
    y, x = np.indices((height, width), dtype=np.float32)
    radial = np.stack((x - width / 2, y - height / 2), axis=2)
    norm = np.linalg.norm(radial, axis=2)
    radial[norm > 0] /= norm[norm > 0, None]
    alignment = abs(float(np.mean(np.sum(vectors * radial[active], axis=1)))) / max(mean_active, 1e-6)
    result.update(median_global_vector_magnitude=median_magnitude,
                  coherence=min(1.0, median_magnitude / max(mean_active, 1e-6)),
                  radial_alignment=alignment)
    return result


def replay_descriptors(path: Path, expected: list[dict]) -> tuple[list[dict], float, dict]:
    """Repeat production flow, checking every label and confidence against Stage 4."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot read normalized video: {path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise ValueError(f"No readable frames: {path}")
        step = max(1, round(fps / motion.MOTION_SAMPLE_RATE_FPS))
        previous = None
        history = []
        samples = []
        frame_number = 0
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number % step:
                frame_number += 1
                continue
            timestamp = frame_number / fps
            scale = min(1.0, 480 / frame.shape[1])
            resized = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            if previous is not None:
                flow = cv2.calcOpticalFlowFarneback(previous, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                kind, confidence, _ = motion._classify_optical_flow(flow, history)
                row = {"timestamp": timestamp, "type": kind, "confidence": confidence,
                       **flow_descriptors(flow)}
                index = len(samples)
                if index >= len(expected) or any(row[key] != expected[index][key]
                                                  for key in ("timestamp", "type", "confidence")):
                    raise ValueError(f"Stage 4 raw classifier drift at sample {index}")
                samples.append(row)
            previous = gray
            frame_number += 1
        if len(samples) != len(expected):
            raise ValueError("Stage 4 sample count drift")
        return samples, frame_count / fps, {"fps": fps, "frame_count": frame_count,
                                           "sample_interval_frames": step,
                                           "sample_interval_seconds": step / fps}
    finally:
        capture.release()


def simplify(sample: dict) -> dict:
    """Retain local only where the unchanged classifier found spatial locality."""
    result = dict(sample)
    if sample["original_type"] is None:
        result["type"] = None
        return result
    if sample["type"] is None:
        return result
    if (sample["type"] == "local_motion" and sample["original_type"] == "local_motion"
            and sample["active_pixel_coverage"] <= 0.4 + 1e-6):
        result["type"] = "local_motion"
    else:
        result["type"] = "motion_present"
    return result


def cut_masked_samples(raw: list[dict], scene: list[dict]) -> list[dict]:
    if len(raw) != len(scene):
        raise ValueError("Scene sample count drift")
    result = []
    for before, after in zip(raw, scene):
        if before["timestamp"] != after["timestamp"]:
            raise ValueError("Scene sample cadence drift")
        sample = dict(before)
        sample["skipped_scene_cuts"] = after["skipped_scene_cuts"]
        if sample["skipped_scene_cuts"]:
            sample["type"] = None
            sample["confidence"] = 0.0
        result.append(sample)
    return result


def simplified_events(samples: list[dict], duration: float, interval: float) -> list[dict]:
    # Suppress on the original classes first, then coalesce formerly distinct
    # nonlocal classes into one neutral evidence state. Never bridge a cut cell.
    stabilized = suppress_preserving_scene_gaps(samples)
    for current, original in zip(stabilized, samples):
        current["original_type"] = original["type"]
    events = runs_to_events([simplify(row) for row in stabilized], duration, interval)
    # The old confidence scores semantic branches. They are not calibrated
    # confidence in this neutral evidence contract.
    return [{key: value for key, value in event.items() if key != "confidence"}
            for event in events]


def attach_event_descriptors(events: list[dict], samples: list[dict], interval: float,
                             *, baseline: bool = False) -> list[dict]:
    result = []
    for event in events:
        contributors = [row for row in samples
                        if not row.get("skipped_scene_cuts")
                        and row["timestamp"] - interval >= event["start"] - 0.002
                        and row["timestamp"] - interval < event["end"] - 1e-9
                        and row["type"] is not None
                        and (not baseline or row["type"] == event["type"])]
        descriptor = {key: (statistics.mean(values) if values else None)
                      for key in DESCRIPTORS
                      for values in [[row[key] for row in contributors if row[key] is not None]]}
        result.append({**event, "duration": event["end"] - event["start"],
                       "sample_count": len(contributors), **descriptor})
    return result


def audit(records: list[dict], sources: dict) -> dict:
    rows = []
    for reviewed in records:
        ref = reviewed["source_ref"]
        support = reviewed["raw_class_support_interval_seconds"]
        cuts = [cut for cut in sources[ref]["production_scene_cuts_seconds"]
                if support[0] + 1e-9 < cut <= support[1] + 1e-9]
        survival = {}
        for name in VARIANTS:
            hits = [event for event in sources[ref]["events"][name] if overlaps(support, event)]
            survival[name] = {"any_event": bool(hits),
                              "local_motion": any(event["type"] == "local_motion" for event in hits),
                              "event_types": sorted({event["type"] for event in hits})}
        rows.append({"audit_id": reviewed["audit_id"], "source_ref": ref,
                     "detector_class": reviewed["detector_class"],
                     "reviewed_class": reviewed["reviewed_class"],
                     "support_seconds": support, "production_cuts_on_support": cuts,
                     "survival": survival})
    summary = {}
    for name in VARIANTS:
        known = [row for row in rows if row["reviewed_class"] != "uncertain"]
        positive = [row for row in known if row["reviewed_class"] in VALID]
        negative = [row for row in known if row["reviewed_class"] == "no_meaningful_motion"]
        tp = sum(row["survival"][name]["any_event"] for row in positive)
        fp = sum(row["survival"][name]["any_event"] for row in negative)
        local_true = [row for row in known if row["reviewed_class"] == "local_subject_motion"]
        local_tp = sum(row["survival"][name]["local_motion"] for row in local_true)
        local_fp = sum(row["survival"][name]["local_motion"] for row in known
                       if row["reviewed_class"] != "local_subject_motion")
        edit_artifacts = [row for row in negative if row["production_cuts_on_support"]]
        summary[name] = {
            "meaningful_motion_presence": {"true_positive": tp, "false_positive": fp,
                                           "false_negative": len(positive) - tp,
                                           "true_negative": len(negative) - fp,
                                           "precision": tp / (tp + fp) if tp + fp else None,
                                           "recall": tp / len(positive) if positive else None},
            "local_motion": {"true_positive": local_tp, "false_positive": local_fp,
                             "false_negative": len(local_true) - local_tp,
                             "precision": local_tp / (local_tp + local_fp) if local_tp + local_fp else None,
                             "recall": local_tp / len(local_true) if local_true else None},
            "visually_valid_retained": tp,
            "no_meaningful_motion_false_positives": fp,
            "cut_associated_no_motion_cases": len(edit_artifacts),
            "cut_associated_no_motion_retained": sum(row["survival"][name]["any_event"]
                                                    for row in edit_artifacts),
        }
    return {"reviewed_count": len(rows), "valid_count": sum(row["reviewed_class"] in VALID for row in rows),
            "no_meaningful_count": sum(row["reviewed_class"] == "no_meaningful_motion" for row in rows),
            "uncertain_count": sum(row["reviewed_class"] == "uncertain" for row in rows),
            "summary": summary, "records": rows}


def aggregate(sources: dict) -> dict:
    duration = sum(source["duration_seconds"] for source in sources.values())
    output = {}
    for name in VARIANTS:
        all_events = [event for source in sources.values() for event in source["events"][name]]
        lengths = [event["duration"] for event in all_events]
        covered = sum(_interval_stats(source["events"][name])[0] for source in sources.values())
        overlap = sum(_interval_stats(source["events"][name])[1] for source in sources.values())
        output[name] = {"total_events": len(all_events), "events_per_minute": 60 * len(all_events) / duration,
                        "median_event_duration_seconds": statistics.median(lengths) if lengths else None,
                        "mean_event_duration_seconds": statistics.mean(lengths) if lengths else None,
                        "video_covered_percent": 100 * covered / duration,
                        "overlapping_event_duration_seconds": overlap,
                        "counts_by_type": {kind: sum(row["type"] == kind for row in all_events)
                                           for kind in sorted({row["type"] for row in all_events})}}
    return output


def run(manifest_path: Path, baseline_dir: Path, stage4_path: Path,
        audit_path: Path, stage4_2_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    stage4 = json.loads(stage4_path.read_text())
    reviewed = json.loads(audit_path.read_text())
    scene_data = json.loads(stage4_2_path.read_text())
    sources = {}
    for item in manifest["sources"]:
        ref = item["source_ref"]
        media_path = Path(item["media_path"])
        source_hash = hashlib.sha256(media_path.read_bytes()).hexdigest()
        baseline = json.loads((baseline_dir / f"{ref}.json").read_text())
        prior = stage4["sources"][ref]
        scene = scene_data["sources"][ref]
        if (baseline["input_sha256"] != source_hash or prior["source_sha256"] != source_hash
                or scene["source_sha256"] != source_hash or not scene["production_scene_output_reproduced"]):
            raise ValueError(f"Pilot source or production scene provenance mismatch: {ref}")
        with tempfile.TemporaryDirectory(prefix=f"cm-stage4-3-{ref}-") as temp:
            normalized = Path(temp) / "normalized.mp4"
            motion.normalise_video(media_path, normalized)
            raw, duration, sampling = replay_descriptors(normalized, prior["raw_samples"])
        if abs(duration - prior["duration_seconds"]) > 1e-6 or sampling != prior["sampling"]:
            raise ValueError(f"Normalized metadata drift: {ref}")
        scene_samples = scene["scene_aware_samples"]
        masked = cut_masked_samples(raw, scene_samples)
        reset = [{**row, "type": after["type"], "confidence": after["confidence"]}
                 for row, after in zip(masked, scene_samples)]
        interval = sampling["sample_interval_seconds"]
        events = {
            "existing_semantic_output": prior["events"]["baseline"],
            "nonoverlap_plus_singleton": prior["events"]["short_run_suppression"],
            "scene_aware_plus_singleton": scene["events"]["scene_aware_reset_plus_suppression"],
            "simplified_cut_mask_plus_singleton": simplified_events(masked, duration, interval),
            "simplified_scene_reset_plus_singleton": simplified_events(reset, duration, interval),
        }
        for name, rows in events.items():
            if name != "existing_semantic_output" and _interval_stats(rows)[1] > 1e-8:
                raise AssertionError(f"Exclusive event overlap: {ref} {name}")
        events = {name: attach_event_descriptors(rows, raw if name in (
                      "existing_semantic_output", "nonoverlap_plus_singleton") else masked, interval,
                                                  baseline=name == "existing_semantic_output")
                  for name, rows in events.items()}
        sources[ref] = {"source_sha256": source_hash, "duration_seconds": duration,
                        "sampling": sampling, "production_scene_cuts_seconds": scene["production_scene_cuts_seconds"],
                        "skipped_flow_pairs": scene["skipped_flow_pairs"],
                        "samples": [{**row, "cut_crossing_excluded": bool(after["skipped_scene_cuts"]),
                                     "scene_reset_type": after["type"]}
                                    for row, after in zip(raw, scene_samples)],
                        "events": events,
                        "metrics": {name: metrics(rows, duration) for name, rows in events.items()}}
    result = {"schema_version": 1, "base_stage4_2_commit": "3feb309ea08d598a0cc9e543deb95b66f7b56d09",
              "scope": "11-video private pilot, offline experiment only",
              "production_files_changed": False, "classifier_thresholds_changed": False,
              "audit_reference": {"records": len(reviewed["records"]),
                                  "review_status": reviewed["review_status"],
                                  "support": "Stage 4.1 raw class support, 1 uncertain excluded from precision/recall"},
              "method": {"scene_cuts": "Stored Stage 4.2 production threshold-27 outputs reproduced against pilot baseline; never repaired truth",
                         "cut_rule": "previous_sample_timestamp < cut_timestamp <= current_sample_timestamp; mask the crossing cell",
                         "simplification": "After A-B-A suppression, keep originally null flow cells as gaps; map existing local_motion with coverage <=0.4 to local_motion, every other non-null class (including unknown) to motion_present",
                         "descriptor_basis": "All-pixel mean magnitude; active-pixel coverage; active median vector magnitude, coherence and radial alignment exactly as classifier computes. Null descriptors where no active pixels.",
                         "event_descriptors": "Arithmetic mean of contributing sample measurements; sample_count counts non-null raw flow cells. Cut-crossing cells excluded. Baseline uses matching original-class cells. Legacy semantic confidence is kept on raw samples and semantic comparators only.",
                         "rounding": "Event times follow existing Stage 4 builders at millisecond precision; descriptors use full-precision replay."},
              "variant_definitions": {
                  "existing_semantic_output": "Exact reconstructed production semantic events, including overlap",
                  "nonoverlap_plus_singleton": "Stage 4 raw-class A-B-A suppression and nonoverlap runs",
                  "scene_aware_plus_singleton": "Stage 4.2 production-cut reset and within-scene A-B-A suppression",
                  "simplified_cut_mask_plus_singleton": "Exclude production-cut crossing flow, preserve raw direction history afterward, suppress within scenes, map to neutral/local evidence",
                  "simplified_scene_reset_plus_singleton": "Exclude production-cut crossing flow, clear direction history, suppress within scenes, map to neutral/local evidence"},
              "recommendation": {"choice": "B", "status": "research_direction_only",
                                 "contract": "raw numeric flow descriptors with motion_present and conservative local_motion; no camera technique claims",
                                 "qualification": "Keep motion out of semantic downstream reasoning until independent review confirms meaningful presence and local specificity"},
              "aggregate": aggregate(sources), "audit": audit(reviewed["records"], sources), "sources": sources}
    return result


def markdown(data: dict) -> str:
    def n(value):
        return "—" if value is None else f"{value:.3f}"

    lines = ["# V9 Stage 4.3 — motion evidence contract experiment", "",
             "Offline only. Production detection, API, schema and classifier thresholds are unchanged. "
             "The 54-event Stage 4.1 review is a small, selected, provisional visual audit; "
             "these figures do not establish population accuracy. One uncertain case is excluded from precision/recall.", "",
             "## Method", "",
             "Flow is replayed with production normalization, 8 FPS sampling and unchanged Farnebäck/classifier settings. "
             "Every raw label, confidence and timestamp must match Stage 4. Stage 4.2 production scene detector cuts "
             "were independently reproduced against stored pilot output at threshold 27. Crossing flow cells are "
             "excluded in both simplified variants; the reset variant also clears direction history. "
             "Singleton suppression runs within cut-separated segments before class mapping; originally null flow "
             "cells remain gaps and cannot become evidence. Local motion survives "
             "only with the existing classifier's local label and coverage at most 0.4. All other non-null classes, "
             "including unknown, become `motion_present`. That neutral state says only that measured flow was present; "
             "it does not imply camera movement or a motion technique.", "",
             "Each sample carries mean flow magnitude over all pixels, active pixel coverage, active median vector "
             "magnitude, coherence and radial alignment. Event descriptors are means over contributing flow cells. "
             "These are observations, not inferred pan/zoom/shake semantics. Null values mean no active pixels. "
             "Simplified events omit legacy semantic confidence; raw samples retain it for provenance. "
             "Event intervals are half-open. JSON contains every sample, event, audit row and per-video metric.", "",
             "## Eleven-video output structure", "",
             "| Variant | Events | Events/min | Median s | Mean s | Runtime coverage % | Overlap s | Counts by type |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for name in VARIANTS:
        row = data["aggregate"][name]
        counts = ", ".join(f"{key} {value}" for key, value in row["counts_by_type"].items())
        lines.append(f"| {name} | {row['total_events']} | {n(row['events_per_minute'])} | "
                     f"{n(row['median_event_duration_seconds'])} | {n(row['mean_event_duration_seconds'])} | "
                     f"{n(row['video_covered_percent'])} | {n(row['overlapping_event_duration_seconds'])} | {counts} |")
    lines += ["", "## Reviewed sample", "",
              "Presence precision/recall treats all visually meaningful review classes as positive and "
              "`no_meaningful_motion` as negative. Local precision/recall uses `local_subject_motion` as positive "
              "and all other determinate labels as negative. A retained event overlaps the raw class support "
              "by more than 1 ms; it need not retain the exact original semantic class.", "",
              "| Variant | Valid retained / 38 | Presence precision | Presence recall | No-motion false positives / 15 | Local precision | Local recall | Cut-associated no-motion retained |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name in VARIANTS:
        row = data["audit"]["summary"][name]
        presence, local = row["meaningful_motion_presence"], row["local_motion"]
        lines.append(f"| {name} | {row['visually_valid_retained']} | {n(presence['precision'])} | "
                     f"{n(presence['recall'])} | {row['no_meaningful_motion_false_positives']} | "
                     f"{n(local['precision'])} | {n(local['recall'])} | "
                     f"{row['cut_associated_no_motion_retained']}/{row['cut_associated_no_motion_cases']} |")
    lines += ["", "## Focus videos", "",
              "| Video | Variant | Events | Coverage % | Median s | Mean s | Overlap s |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for ref in ("04", "07", "09", "12"):
        for name in VARIANTS:
            row = data["sources"][ref]["metrics"][name]
            lines.append(f"| {ref} | {name} | {row['total_events']} | {n(row['video_covered_percent'])} | "
                         f"{n(row['median_event_duration_seconds'])} | {n(row['mean_event_duration_seconds'])} | "
                         f"{n(row['overlapping_event_duration_seconds'])} |")
    lines += ["", "## Video 09 reviewed cases", "",
              "| Audit ID | Review | Production cut on support | " + " | ".join(VARIANTS) + " |",
              "| --- | --- | --- | " + " | ".join(["---"] * len(VARIANTS)) + " |"]
    for row in data["audit"]["records"]:
        if row["source_ref"] == "09":
            lines.append("| " + " | ".join([str(row["audit_id"]), row["reviewed_class"],
                                                str(bool(row["production_cuts_on_support"]))] +
                                               ["yes" if row["survival"][name]["any_event"] else "no"
                                                for name in VARIANTS]) + " |")
    simple = data["audit"]["summary"]["simplified_scene_reset_plus_singleton"]
    local = simple["local_motion"]
    presence = simple["meaningful_motion_presence"]
    same_events = all(source["events"][VARIANTS[3]] == source["events"][VARIANTS[4]]
                      for source in data["sources"].values())
    lines += ["", "## Interpretation and recommendation", "",
              "The current semantic pan/zoom/shake/general labels failed Stage 4.1's exact-class review; "
              "scene reset removed edit artifacts but did not rescue those meanings. The neutral contract "
              "should be judged on motion presence and spatial locality only. Cut-associated cases are "
              "identified by the production detector, not repaired truth. The selected audit and its "
              "single-review provenance limit confidence in precision/recall estimates.", "",
              f"The simplified variant retains {presence['true_positive']}/38 visually valid cases, but also "
              f"retains {presence['false_positive']}/15 reviewed no-motion cases. Its local label is correct "
              f"in {local['true_positive']}/{local['true_positive'] + local['false_positive']} emitted reviewed "
              f"local cases and finds only {local['true_positive']}/{local['true_positive'] + local['false_negative']} "
              "visually local cases. Local is therefore a sparse positive signal, not a complete subject-motion detector. "
              f"The two simplified variants {'have identical event intervals and labels across all 11 videos' if same_events else 'differ in event output'}; "
              "the cut mask, rather than direction reset, determines this coarse contract in the pilot.", "",
              "**Recommendation: B — use the simplified low-level contract as the V9 research direction.** "
              "Keep motion out of semantic downstream reasoning until independent review confirms meaningful "
              "presence and local specificity. If it fails that review, choose C and omit motion. A is unsupported "
              "by the reviewed class results. No production integration is authorized or made here.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--stage4", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--stage4-2", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.manifest, args.baseline_dir, args.stage4, args.audit, args.stage4_2)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "motion_contract_experiment.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output_dir / "motion_contract_experiment.md").write_text(markdown(result))
    print(json.dumps({name: row["total_events"] for name, row in result["aggregate"].items()}))


if __name__ == "__main__":
    main()
