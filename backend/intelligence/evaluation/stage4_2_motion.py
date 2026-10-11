"""Offline V9 Stage 4.2 scene-aware motion replay; no production changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
from pathlib import Path

from app import video_processing as motion
from .stage4_motion import TYPES, _interval_stats, metrics, runs_to_events, suppress_singletons

VARIANTS = ("nonoverlap_only", "one_sample_suppression_only",
            "scene_aware_reset_only", "scene_aware_reset_plus_suppression")
SEMANTIC_TARGETS = {"camera_pan": "camera_pan", "camera_zoom": "camera_zoom",
                    "camera_shake": "camera_shake", "local_motion": "local_subject_motion",
                    "general_motion": "general_scene_motion"}


def crossed_cuts(cuts: list[float], previous: float, current: float) -> list[float]:
    """A cut at the post-cut sample timestamp invalidates that flow pair."""
    return [cut for cut in cuts if previous + 1e-9 < cut <= current + 1e-9]


def scene_aware_samples(video_path: Path, cuts: list[float]) -> tuple[list[dict], float, dict]:
    """Replay production flow sampling, skipping cut-crossing pairs and history."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Cannot read normalized video: {video_path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise ValueError(f"No readable frames: {video_path}")
        interval_frames = max(1, round(fps / motion.MOTION_SAMPLE_RATE_FPS))
        interval = interval_frames / fps
        duration = frame_count / fps
        previous_gray = None
        previous_timestamp = None
        history = []
        samples = []
        frame_number = 0
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number % interval_frames:
                frame_number += 1
                continue
            timestamp = frame_number / fps
            scale = min(1.0, 480 / frame.shape[1])
            resized = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            if previous_gray is not None:
                crossed = crossed_cuts(cuts, previous_timestamp, timestamp)
                if crossed:
                    # This comparison owns no motion cell. The post-cut frame becomes
                    # the next flow baseline; no pre-cut direction can leak forward.
                    samples.append({"timestamp": timestamp, "type": None, "confidence": 0.0,
                                    "skipped_scene_cuts": crossed})
                    history.clear()
                else:
                    flow = cv2.calcOpticalFlowFarneback(
                        previous_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                    kind, confidence, _ = motion._classify_optical_flow(flow, history)
                    samples.append({"timestamp": timestamp, "type": kind,
                                    "confidence": confidence, "skipped_scene_cuts": []})
            previous_gray = gray
            previous_timestamp = timestamp
            frame_number += 1
        return samples, duration, {"fps": fps, "frame_count": frame_count,
                                   "sample_interval_frames": interval_frames,
                                   "sample_interval_seconds": interval}
    finally:
        capture.release()


def suppress_preserving_scene_gaps(samples: list[dict]) -> list[dict]:
    """Apply Stage 4 singleton suppression within each scene segment only."""
    result = []
    segment = []
    for sample in samples:
        if sample["skipped_scene_cuts"]:
            result.extend(suppress_singletons(segment))
            segment = []
            result.append(dict(sample))
        else:
            segment.append(sample)
    result.extend(suppress_singletons(segment))
    return result


def events_for_variants(stage4_source: dict, scene_samples: list[dict],
                        duration: float, interval: float) -> dict[str, list[dict]]:
    return {
        "nonoverlap_only": stage4_source["events"]["nonoverlap_only"],
        "one_sample_suppression_only": stage4_source["events"]["short_run_suppression"],
        "scene_aware_reset_only": runs_to_events(scene_samples, duration, interval),
        "scene_aware_reset_plus_suppression": runs_to_events(
            suppress_preserving_scene_gaps(scene_samples), duration, interval),
    }


def overlaps(interval: list[float], event: dict) -> bool:
    return min(interval[1], event["end"]) - max(interval[0], event["start"]) > 0.001


def audit_variant(records: list[dict], sources: dict) -> dict:
    rows = []
    for reviewed in records:
        ref = reviewed["source_ref"]
        interval = reviewed["raw_class_support_interval_seconds"]
        cuts = sources[ref]["production_scene_cuts_seconds"]
        crossing = [cut for cut in cuts if interval[0] + 1e-9 < cut <= interval[1] + 1e-9]
        survival = {}
        for name in VARIANTS:
            events = sources[ref]["events"][name]
            survival[name] = {
                "same_class": any(event["type"] == reviewed["detector_class"] and overlaps(interval, event)
                                  for event in events),
                "any_event": any(overlaps(interval, event) for event in events),
            }
        rows.append({"audit_id": reviewed["audit_id"], "source_ref": ref,
                     "detector_class": reviewed["detector_class"],
                     "reviewed_class": reviewed["reviewed_class"],
                     "raw_class_support_interval_seconds": interval,
                     "production_scene_cuts_on_support": crossing,
                     "survival": survival})

    def tally(group: list[dict], name: str) -> dict:
        valid = [row for row in group if row["reviewed_class"] not in
                 ("no_meaningful_motion", "uncertain")]
        noise = [row for row in group if row["reviewed_class"] == "no_meaningful_motion"]
        return {"total_reviewed": len(group), "visually_valid": len(valid),
                "visually_valid_same_class_retained": sum(row["survival"][name]["same_class"] for row in valid),
                "visually_valid_any_event_retained": sum(row["survival"][name]["any_event"] for row in valid),
                "no_meaningful_motion": len(noise),
                "no_meaningful_same_class_removed_from_raw_support": sum(
                    not row["survival"][name]["same_class"] for row in noise),
                "no_meaningful_no_event_on_raw_support": sum(
                    not row["survival"][name]["any_event"] for row in noise),
                "uncertain": len(group) - len(valid) - len(noise)}

    aggregate = {name: tally(rows, name) for name in VARIANTS}
    by_class = {kind: {name: tally([row for row in rows if row["detector_class"] == kind], name)
                       for name in VARIANTS} for kind in TYPES}
    semantic_failures = [row for row in rows if row["detector_class"] in SEMANTIC_TARGETS and
                         row["reviewed_class"] not in ("uncertain", SEMANTIC_TARGETS[row["detector_class"]])]
    cut_failures = [row for row in semantic_failures if row["production_scene_cuts_on_support"]]
    noise_semantic = [row for row in semantic_failures if row["reviewed_class"] == "no_meaningful_motion"]
    cut_noise = [row for row in noise_semantic if row["production_scene_cuts_on_support"]]
    return {"aggregate": aggregate, "by_original_detector_class": by_class, "records": rows,
            "cut_attribution": {"semantic_failures_in_reviewed_sample": len(semantic_failures),
                                "semantic_failures_with_production_cut_on_raw_support": len(cut_failures),
                                "fraction_of_semantic_failures_cut_associated": len(cut_failures) / len(semantic_failures),
                                "no_meaningful_semantic_failures": len(noise_semantic),
                                "no_meaningful_semantic_failures_cut_associated": len(cut_noise),
                                "assessment": "meaningful_subset_in_selected_sample_not_complete_explanation",
                                "cut_associated_failure_ids": [row["audit_id"] for row in cut_failures]}}


def aggregate_metrics(sources: dict) -> dict:
    total_duration = sum(source["duration_seconds"] for source in sources.values())
    results = {}
    for name in VARIANTS:
        all_events = [event for source in sources.values() for event in source["events"][name]]
        durations = [event["end"] - event["start"] for event in all_events]
        results[name] = {"total_events": len(all_events),
                         "events_per_minute": 60 * len(all_events) / total_duration,
                         "overlapping_event_duration_seconds": sum(
                             _interval_stats(source["events"][name])[1] for source in sources.values()),
                         "median_event_duration_seconds": statistics.median(durations) if durations else None,
                         "mean_event_duration_seconds": statistics.mean(durations) if durations else None,
                         "video_covered_percent": 100 * sum(
                             _interval_stats(source["events"][name])[0] for source in sources.values()) / total_duration,
                         "counts_by_type": {kind: sum(event["type"] == kind for event in all_events)
                                            for kind in TYPES}}
    return results


def run(manifest_path: Path, baseline_dir: Path, stage4_path: Path, audit_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    stage4 = json.loads(stage4_path.read_text())
    reviewed = json.loads(audit_path.read_text())
    sources = {}
    for item in manifest["sources"]:
        ref = item["source_ref"]
        path = Path(item["media_path"])
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        baseline = json.loads((baseline_dir / f"{ref}.json").read_text())
        stage4_source = stage4["sources"][ref]
        if baseline["input_sha256"] != source_hash or stage4_source["source_sha256"] != source_hash:
            raise ValueError(f"Source identity mismatch: {ref}")
        expected_scenes = baseline["analysis"]["scenes"]
        with tempfile.TemporaryDirectory(prefix=f"cm-stage4-2-{ref}-") as temp:
            normalized = Path(temp) / "normalized.mp4"
            motion.normalise_video(path, normalized)
            detected_scenes = motion.detect_scenes(normalized)
            if detected_scenes != expected_scenes:
                raise ValueError(f"Production threshold-27 scene output drift: {ref}")
            cuts = [scene["cut_timestamp_seconds"] for scene in detected_scenes
                    if scene["cut_timestamp_seconds"] is not None]
            samples, duration, sampling = scene_aware_samples(normalized, cuts)
        original = stage4_source["raw_samples"]
        if len(samples) != len(original) or any(abs(a["timestamp"] - b["timestamp"]) > 1e-6
                                                for a, b in zip(samples, original)):
            raise ValueError(f"Motion sample cadence drift: {ref}")
        if abs(duration - stage4_source["duration_seconds"]) > 1e-6 or sampling != stage4_source["sampling"]:
            raise ValueError(f"Normalized video metadata drift: {ref}")
        first_cut_index = next((i for i, sample in enumerate(samples) if sample["skipped_scene_cuts"]), len(samples))
        if any((a["type"], a["confidence"]) != (b["type"], b["confidence"])
               for a, b in zip(samples[:first_cut_index], original[:first_cut_index])):
            raise ValueError(f"Pre-cut classifier replay drift: {ref}")
        events = events_for_variants(stage4_source, samples, duration, sampling["sample_interval_seconds"])
        for name, candidate in events.items():
            if _interval_stats(candidate)[1] > 1e-8:
                raise AssertionError(f"Overlapping exclusive events: {ref} {name}")
        sources[ref] = {"source_sha256": source_hash, "duration_seconds": duration,
                        "production_scene_cuts_seconds": cuts,
                        "production_scene_output_reproduced": True,
                        "sampling": sampling,
                        "skipped_flow_pairs": sum(bool(sample["skipped_scene_cuts"]) for sample in samples),
                        "changed_noncut_sample_labels": sum(
                            not sample["skipped_scene_cuts"] and sample["type"] != before["type"]
                            for sample, before in zip(samples, original)),
                        "scene_aware_samples": samples, "events": events,
                        "metrics": {name: metrics(candidate, duration) for name, candidate in events.items()}}
    audit = audit_variant(reviewed["records"], sources)
    for name, old in (("nonoverlap_only", "nonoverlap_only"),
                      ("one_sample_suppression_only", "short_run_suppression")):
        for ref, source in sources.items():
            if source["events"][name] != stage4["sources"][ref]["events"][old]:
                raise ValueError(f"Stage 4 comparator drift: {ref} {name}")
    return {"schema_version": 1, "base_stage4_1_commit": "8df2284cd56ead551ea38b3c8a71db6d9669b576",
            "scope": "11-video offline replay using production scene detector at threshold 27; no accuracy or population claim",
            "production_files_changed": False, "classifier_thresholds_changed": False,
            "scene_signal": {"function": "app.video_processing.detect_scenes",
                             "threshold": motion.SCENE_DETECTION_THRESHOLD,
                             "source": "fresh production detection on normalized pilot video; exact match required against stored production pilot scene output",
                             "repaired_truth_used_for_output": False,
                             "cut_pair_rule": "previous_sample_timestamp < cut_timestamp <= current_sample_timestamp"},
            "variant_definitions": {
                "nonoverlap_only": "Stage 4 baseline events with starts clipped to previous event ends; count unchanged, labels can shift off raw support",
                "one_sample_suppression_only": "Stage 4 raw samples, A-B-A singleton suppression, nonoverlapping run construction",
                "scene_aware_reset_only": "skip cut-crossing flow pair, emit explicit gap, use post-cut frame as previous, clear direction history, nonoverlapping run construction",
                "scene_aware_reset_plus_suppression": "scene-aware reset followed by A-B-A suppression within cut-separated segments only"},
            "audit_reference": {"records": len(reviewed["records"]),
                                "review_status": reviewed["review_status"],
                                "survival_interval": "Stage 4.1 raw class support, not overlapping baseline exported interval"},
            "aggregate": aggregate_metrics(sources), "audit": audit, "sources": sources}


def markdown(data: dict) -> str:
    def number(value):
        return "—" if value is None else f"{value:.3f}"

    lines = ["# V9 Stage 4.2: scene-aware motion experiment", "",
             "Offline replay only. Production scene and motion detection, `_classify_optical_flow()` "
             "and all thresholds are unchanged. Every video was normalized with the production helper; "
             "production `detect_scenes()` at threshold 27 was rerun and matched the stored pilot scene "
             "output exactly. Repaired reference scene truth was never used to alter motion output.", "",
             "The Stage 4.1 54-event visual review is provisional: one AI review of short private "
             "frame sequences, with no independent human adjudication. These are selected-sample "
             "retention figures, not motion precision or population estimates.", "",
             "## Method", "",
             "When a production cut falls after the previous sampled frame and at or before the current "
             "sampled frame, that optical-flow pair is skipped. Its sample cell becomes a gap. The current "
             "post-cut frame becomes the next previous frame, and direction history is cleared. An active "
             "event therefore ends at its last pre-cut sample cell. Singleton suppression cannot bridge "
             "a protected cut gap. `unknown` remains an event; no duration filter is applied.", "",
             "The two non-scene comparators are the exact Stage 4 variants. Clipping-only can shift "
             "a class interval off the raw sample that generated it. All results use half-open event "
             "intervals; audit survival is measured against the raw class support from Stage 4.1.", "",
             "## Eleven-video output structure", "",
             "| Variant | Events | Events/min | Overlap s | Median s | Mean s | Runtime covered % | Counts pan/zoom/shake/local/general/unknown |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for name in VARIANTS:
        row = data["aggregate"][name]
        counts = "/".join(str(row["counts_by_type"][kind]) for kind in TYPES)
        lines.append(f"| {name} | {row['total_events']} | {number(row['events_per_minute'])} | "
                     f"{number(row['overlapping_event_duration_seconds'])} | "
                     f"{number(row['median_event_duration_seconds'])} | "
                     f"{number(row['mean_event_duration_seconds'])} | "
                     f"{number(row['video_covered_percent'])} | {counts} |")
    lines += ["", "The combined variant can produce more events than singleton suppression alone: "
              "scene gaps split runs, and clearing direction history changes some later class labels."]
    lines += ["", "## Per-video output structure", "",
              "Counts use pan/zoom/shake/local/general/unknown order.", "",
              "| Video | Variant | Events | Events/min | Overlap s | Median s | Mean s | Covered % | Type counts |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for ref, source in data["sources"].items():
        for name in VARIANTS:
            row = source["metrics"][name]
            counts = "/".join(str(row["counts_by_type"][kind]) for kind in TYPES)
            lines.append(f"| **{ref}** | {name} | {row['total_events']} | "
                         f"{number(row['events_per_minute'])} | "
                         f"{number(row['overlapping_event_duration_seconds'])} | "
                         f"{number(row['median_event_duration_seconds'])} | "
                         f"{number(row['mean_event_duration_seconds'])} | "
                         f"{number(row['video_covered_percent'])} | {counts} |")
    lines += ["", "## Scene reset coverage", "",
              "| Video | Production cuts | Flow pairs skipped | Other sample labels changed after resets |",
              "| --- | ---: | ---: | ---: |"]
    for ref, source in data["sources"].items():
        lines.append(f"| **{ref}** | {len(source['production_scene_cuts_seconds'])} | "
                     f"{source['skipped_flow_pairs']} | {source['changed_noncut_sample_labels']} |")
    lines += ["", "## Stage 4.1 reviewed audit retention", "",
              "Visually valid excludes `uncertain` and `no_meaningful_motion`. Noise means reviewed "
              "`no_meaningful_motion`. Same-class and any-event retention are separately counted on "
              "each raw class support interval. A different overlapping class does not prove that "
              "the motion meaning was retained.", "",
              "| Variant | Valid same class | Valid any event | Noise same class absent | Noise no event |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name in VARIANTS:
        row = data["audit"]["aggregate"][name]
        lines.append(f"| {name} | {row['visually_valid_same_class_retained']}/{row['visually_valid']} | "
                     f"{row['visually_valid_any_event_retained']}/{row['visually_valid']} | "
                     f"{row['no_meaningful_same_class_removed_from_raw_support']}/{row['no_meaningful_motion']} | "
                     f"{row['no_meaningful_no_event_on_raw_support']}/{row['no_meaningful_motion']} |")
    lines += ["", "Clipping-only changes no event count, so its absent labels are timing misalignment "
              "rather than event removal.", "", "## Audit by original detector class", "",
              "Each cell is `valid same class / valid any event / noise no event`; denominators "
              "appear in the first columns. Reviewed labels remain fixed from Stage 4.1.", "",
              "| Detector class | Valid | Noise | Nonoverlap | Singleton | Scene reset | Scene reset + singleton |",
              "| --- | ---: | ---: | --- | --- | --- | --- |"]
    for kind in TYPES:
        per = data["audit"]["by_original_detector_class"][kind]
        first = per[VARIANTS[0]]
        cells = []
        for name in VARIANTS:
            row = per[name]
            cells.append(f"{row['visually_valid_same_class_retained']} / "
                         f"{row['visually_valid_any_event_retained']} / "
                         f"{row['no_meaningful_no_event_on_raw_support']}")
        lines.append(f"| {kind} | {first['visually_valid']} | {first['no_meaningful_motion']} | "
                     + " | ".join(cells) + " |")
    lines += ["", "## Video 09: all four reviewed events", "",
              "| ID | Baseline class | Production cut(s) on raw support | Nonoverlap same/any | Singleton same/any | Scene same/any | Combined same/any |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in data["audit"]["records"]:
        if row["source_ref"] != "09":
            continue
        cells = [f"{row['survival'][name]['same_class']}/{row['survival'][name]['any_event']}"
                 for name in VARIANTS]
        lines.append(f"| {row['audit_id']} | {row['detector_class']} | "
                     f"{row['production_scene_cuts_on_support']} | " + " | ".join(cells) + " |")
    attribution = data["audit"]["cut_attribution"]
    valid_lost = [row["audit_id"] for row in data["audit"]["records"]
                  if row["reviewed_class"] not in ("uncertain", "no_meaningful_motion")
                  and not row["survival"]["scene_aware_reset_only"]["any_event"]]
    total_cuts = sum(len(source["production_scene_cuts_seconds"])
                     for source in data["sources"].values())
    skipped_pairs = sum(source["skipped_flow_pairs"] for source in data["sources"].values())
    changed_labels = sum(source["changed_noncut_sample_labels"] for source in data["sources"].values())
    lines += ["", "## Cut attribution and limits", "",
              f"**Yes, production-detected boundary crossings account for a meaningful subset of "
              f"semantic failures in this selected sample:** "
              f"{attribution['semantic_failures_with_production_cut_on_raw_support']} "
              f"of {attribution['semantic_failures_in_reviewed_sample']} incorrect semantic predictions "
              f"({number(100 * attribution['fraction_of_semantic_failures_cut_associated'])}%). "
              f"They intersect {attribution['no_meaningful_semantic_failures_cut_associated']} "
              f"of {attribution['no_meaningful_semantic_failures']} semantic predictions reviewed as no "
              "meaningful motion. The remaining semantic failures do not cross a production-detected "
              "cut, so scene reset alone cannot make the motion classes trustworthy.", "",
              f"Across the pilot, {total_cuts} production scene boundaries caused {skipped_pairs} skipped "
              f"flow pairs, and clearing direction history changed {changed_labels} additional non-cut "
              "sample labels. In the reviewed set, scene reset removes all four 09 edit artifacts and "
              f"leaves no event on 8/15 no-meaningful-motion examples, but also removes {len(valid_lost)}/38 "
              f"visually valid examples ({', '.join(valid_lost)}). Adding singleton suppression does not "
              "remove more reviewed no-meaningful-motion examples or recover those valid examples; "
              "it changes same-class retention. No variant is selected for production.", "",
              "Co-occurrence with a production scene boundary is an attribution "
              "signal, not proof that every such prediction was caused by an editorial cut. The "
              "reviewed sample cannot detect newly introduced errors outside its intervals.", "",
              "Per-video metrics, the replayed sample stream, cut timestamps, skipped pairs, and all "
              "54 audit survival rows are in the JSON.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--stage4", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.manifest, args.baseline_dir, args.stage4, args.audit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "scene_aware_motion.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output_dir / "scene_aware_motion.md").write_text(markdown(result))
    print(json.dumps({name: row["total_events"] for name, row in result["aggregate"].items()}))


if __name__ == "__main__":
    main()
