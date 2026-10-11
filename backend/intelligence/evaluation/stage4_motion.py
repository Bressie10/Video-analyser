"""Offline V9 motion event stabilization; production detector is untouched."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import tempfile
from pathlib import Path

from app import video_processing as motion

TYPES = ("camera_pan", "camera_zoom", "camera_shake", "local_motion", "general_motion", "unknown")
CONFIGS = ("baseline", "nonoverlap_only", "merge_identical", "short_run_suppression",
           "min_0.25", "min_0.5", "min_0.75", "unknown_as_gap", "unknown_gap_min_0.5")


def sample_video(path: Path) -> tuple[list[dict], float, dict]:
    """Repeat the production sampling and flow call, retaining every classification."""
    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot read normalized video: {path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps <= 0 or frame_count <= 0:
            raise ValueError(f"No readable frames: {path}")
        interval_frames = max(1, round(fps / motion.MOTION_SAMPLE_RATE_FPS))
        interval = interval_frames / fps
        duration = frame_count / fps
        previous_gray = None
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
                flow = cv2.calcOpticalFlowFarneback(
                    previous_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                kind, confidence, _ = motion._classify_optical_flow(flow, history)
                samples.append({"timestamp": timestamp, "type": kind, "confidence": confidence})
            previous_gray = gray
            frame_number += 1
        return samples, duration, {"fps": fps, "frame_count": frame_count,
                                   "sample_interval_frames": interval_frames,
                                   "sample_interval_seconds": interval}
    finally:
        capture.release()


def baseline_events(samples: list[dict], duration: float, interval: float) -> list[dict]:
    """Reconstruct detect_motion_events event handling exactly from raw samples."""
    events = []
    active = None
    for sample in samples:
        timestamp = sample["timestamp"]
        kind = sample["type"]
        confidence = sample["confidence"]
        if kind is None:
            if active is not None:
                active["end"] = round(timestamp, 3)
                events.append(_finish(active))
                active = None
        elif active is not None and active["type"] == kind:
            active["end"] = round(timestamp, 3)
            active["confidence_total"] += confidence
            active["samples"] += 1
        else:
            if active is not None:
                active["end"] = round(timestamp, 3)
                events.append(_finish(active))
            active = {"start": round(timestamp - interval, 3), "end": round(timestamp, 3),
                      "type": kind, "confidence_total": confidence, "samples": 1}
    if active is not None:
        active["end"] = round(duration, 3)
        events.append(_finish(active))
    return events


def _finish(active: dict) -> dict:
    active["confidence"] = round(active.pop("confidence_total") / active.pop("samples"), 3)
    return active


def nonoverlap_only(events: list[dict]) -> list[dict]:
    result = []
    for event in events:
        start = max(event["start"], result[-1]["end"] if result else 0)
        if event["end"] > start:
            result.append({**event, "start": start})
    return result


def suppress_singletons(samples: list[dict]) -> list[dict]:
    result = [dict(sample) for sample in samples]
    original = [sample["type"] for sample in samples]
    index = 1
    while index < len(samples) - 1:
        if original[index - 1] == original[index + 1] != original[index]:
            result[index]["type"] = original[index - 1]
            index += 2  # avoid conflicting replacements in an alternating sequence
        else:
            index += 1
    return result


def runs_to_events(samples: list[dict], duration: float, interval: float,
                   *, min_duration: float = 0, unknown_gap: bool = False) -> list[dict]:
    """Build half-open intervals from sample cells; gaps remain explicit."""
    events = []
    if not samples:
        return events
    run_start = 0
    for index in range(1, len(samples) + 1):
        if index < len(samples) and samples[index]["type"] == samples[run_start]["type"]:
            continue
        kind = samples[run_start]["type"]
        start = round(samples[run_start]["timestamp"] - interval, 3)
        end = (round(samples[index]["timestamp"] - interval, 3)
               if index < len(samples) else round(duration, 3))
        if kind is not None and not (unknown_gap and kind == "unknown") and end - start >= min_duration - 1e-9:
            confidences = [sample["confidence"] for sample in samples[run_start:index]
                           if sample["type"] == kind]
            events.append({"start": start, "end": end, "type": kind,
                           "confidence": round(statistics.mean(confidences), 3)})
        run_start = index
    return events


def configurations(samples: list[dict], duration: float, interval: float) -> dict[str, list[dict]]:
    baseline = baseline_events(samples, duration, interval)
    stable = suppress_singletons(samples)
    return {
        "baseline": baseline,
        "nonoverlap_only": nonoverlap_only(baseline),
        "merge_identical": runs_to_events(samples, duration, interval),
        "short_run_suppression": runs_to_events(stable, duration, interval),
        **{f"min_{minimum}": runs_to_events(stable, duration, interval, min_duration=minimum)
           for minimum in (0.25, 0.5, 0.75)},
        "unknown_as_gap": runs_to_events(stable, duration, interval, unknown_gap=True),
        "unknown_gap_min_0.5": runs_to_events(stable, duration, interval,
                                               min_duration=0.5, unknown_gap=True),
    }


def _interval_stats(events: list[dict]) -> tuple[float, float]:
    boundaries = sorted([(event["start"], 1) for event in events] +
                        [(event["end"], -1) for event in events])
    active = 0
    previous = None
    covered = overlap = 0.0
    for time, delta in boundaries:
        if previous is not None:
            if active > 0:
                covered += time - previous
            if active > 1:
                overlap += time - previous
        active += delta
        previous = time
    return covered, overlap


def metrics(events: list[dict], duration: float) -> dict:
    durations = [event["end"] - event["start"] for event in events]
    covered, overlap = _interval_stats(events)
    return {"total_events": len(events), "events_per_minute": 60 * len(events) / duration,
            "median_event_duration_seconds": statistics.median(durations) if durations else None,
            "mean_event_duration_seconds": statistics.mean(durations) if durations else None,
            "video_covered_percent": 100 * covered / duration,
            "overlapping_event_duration_seconds": overlap,
            "counts_by_type": {kind: sum(event["type"] == kind for event in events) for kind in TYPES}}


def report(sources: dict) -> dict:
    aggregate = {}
    for config in CONFIGS:
        all_events = [event for source in sources.values() for event in source["events"][config]]
        total_duration = sum(source["duration_seconds"] for source in sources.values())
        durations = [event["end"] - event["start"] for event in all_events]
        aggregate[config] = {
            "total_events": len(all_events), "events_per_minute": 60 * len(all_events) / total_duration,
            "median_event_duration_seconds": statistics.median(durations) if durations else None,
            "mean_event_duration_seconds": statistics.mean(durations) if durations else None,
            "video_covered_percent": 100 * sum(_interval_stats(source["events"][config])[0]
                                                for source in sources.values()) / total_duration,
            "overlapping_event_duration_seconds": sum(_interval_stats(source["events"][config])[1]
                                                      for source in sources.values()),
            "counts_by_type": {kind: sum(event["type"] == kind for event in all_events) for kind in TYPES},
        }
    return {"schema_version": 1, "scope": "11-video offline pilot; no motion ground truth or accuracy claim",
            "production_motion_changed": False, "configurations": list(CONFIGS),
            "definitions": {"sample": "One classified Farneback flow comparison at production sampling cadence; null is no detected motion.",
                            "interval": "Half-open [start,end); for corrected events a class owns its sample cell, with the final run extended to video duration.",
                            "short_run_suppression": "A single A-B-A sample is relabeled A, including null/unknown; scan left to right without adjacent conflicting replacements.",
                            "minimum_duration": "After singleton suppression, omit runs shorter than the named duration; do not bridge resulting gaps.",
                            "unknown_as_gap": "After singleton suppression, omit unknown runs rather than emitting them.",
                            "coverage": "Union of emitted event intervals divided by summed video duration.",
                            "overlap": "Time with at least two emitted events, calculated from interval endpoints."},
            "invariant": {"mutually_exclusive_corrected_events_do_not_overlap": True,
                          "checked_configurations": list(CONFIGS[1:])},
            "aggregate": aggregate, "sources": sources}


def markdown(data: dict) -> str:
    names = data["configurations"]
    def n(value):
        return "—" if value is None else f"{value:.3f}"
    lines = ["# V9 Stage 4: offline motion event stabilization", "",
             "Production `_classify_optical_flow()` and `detect_motion_events()` are unchanged. "
             "The 11 source videos are 01 and 03–12; 02 is not in the pilot. "
             "The experiment repeats production normalization, sampling, Farnebäck flow and classification. "
             "Every reconstructed baseline event was compared to its stored pilot event.", "",
             "No independent motion ground truth is available. Event count, duration, coverage and overlap "
             "measure output structure, not motion accuracy.", "",
             "## Method", "",
             "Each raw record contains comparison timestamp, predicted type (null means no motion), and confidence. "
             "Corrected intervals are half-open sample cells. The final class run extends to video duration, "
             "as in production. Baseline is the current event builder. Nonoverlap clips the start of each "
             "baseline event to the previous end. Merge identical builds maximal runs from raw cells; "
             "production already merges consecutive identical labels, so event counts may be unchanged. "
             "Singleton suppression replaces A-B-A with A-A-A, scanning left to right and skipping "
             "adjacent conflicting replacements. Confidence remains the original sample confidence. Minimum durations "
             "apply after singleton suppression and discard short runs as gaps. Unknown-as-gap also follows "
             "singleton suppression; the combined 0.5 s variant applies both filters.", "",
             "Coverage is the union of emitted event intervals / total video duration. Overlap is time "
             "covered by at least two events. All per-video and aggregate values are in the JSON.", "",
             "## Aggregate results", "",
             "| Configuration | Events | Events/min | Median s | Mean s | Coverage % | Overlap s | Counts by type |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for name in names:
        row = data["aggregate"][name]
        counts = ", ".join(f"{kind} {count}" for kind, count in row["counts_by_type"].items())
        lines.append(f"| {name} | {row['total_events']} | {n(row['events_per_minute'])} | "
                     f"{n(row['median_event_duration_seconds'])} | {n(row['mean_event_duration_seconds'])} | "
                     f"{n(row['video_covered_percent'])} | {n(row['overlapping_event_duration_seconds'])} | {counts} |")
    lines += ["", "The baseline counts match the stored pilot exactly: 1,351 overall, 394 for 04 "
              "and 350 for 07. Its overlap is 169.244 s. Clipping intervals alone removes overlap "
              "without changing event count. Rebuilding maximal raw-class runs also removes the "
              "baseline's extra coverage of the first no-motion sample after a run. The 0.5 s filter "
              "removes all camera_shake events in this pilot; this is a loss of output, not evidence "
              "that those samples were incorrect.", "",
              "## Focus videos", "",
              "| Video | Baseline | Singleton suppression | Minimum 0.5 s | Unknown as gap |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for ref in ("04", "07", "09", "12"):
        source = data["sources"][ref]
        lines.append(f"| **{ref}** | " + " | ".join(
            str(source["metrics"][name]["total_events"])
            for name in ("baseline", "short_run_suppression", "min_0.5", "unknown_as_gap")) + " |")
    lines += ["", "Video 09 has four baseline events and none after singleton suppression. "
              "The per-video table below shows duration, coverage, overlap and type counts for every "
              "configuration, including 04, 07, 09 and 12.", ""]
    lines += ["", "## Per-video results", "",
              "Each row reports all requested metrics. Type counts use pan/zoom/shake/local/general/unknown order.", "",
              "| Video | Configuration | Events | Events/min | Median s | Mean s | Coverage % | Overlap s | Type counts |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for ref, source in data["sources"].items():
        for name in names:
            row = source["metrics"][name]
            counts = "/".join(str(row["counts_by_type"][kind]) for kind in TYPES)
            lines.append(f"| **{ref}** | {name} | {row['total_events']} | {n(row['events_per_minute'])} | "
                         f"{n(row['median_event_duration_seconds'])} | {n(row['mean_event_duration_seconds'])} | "
                         f"{n(row['video_covered_percent'])} | "
                         f"{n(row['overlapping_event_duration_seconds'])} | {counts} |")
    lines += ["", "## Invariant and interpretation", "",
              "Every corrected configuration has zero overlap between mutually exclusive class events; "
              "the raw baseline overlap is recorded above. No production configuration is selected. "
              "The experiment does not establish which motion labels are correct.", ""]
    return "\n".join(lines)


def run(manifest_path: Path, baseline_dir: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    sources = {}
    for item in manifest["sources"]:
        ref = item["source_ref"]
        source_path = Path(item["media_path"])
        baseline = json.loads((baseline_dir / f"{ref}.json").read_text())
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if baseline["source_ref"] != ref or baseline["input_sha256"] != source_hash:
            raise ValueError(f"Baseline source mismatch: {ref}")
        with tempfile.TemporaryDirectory(prefix=f"cm-stage4-{ref}-") as temp:
            normalized = Path(temp) / "normalized.mp4"
            motion.normalise_video(source_path, normalized)
            samples, duration, sampling = sample_video(normalized)
        events = configurations(samples, duration, sampling["sample_interval_seconds"])
        expected = [{"start": event["start_seconds"], "end": event["end_seconds"],
                     "type": event["type"], "confidence": event["confidence"]}
                    for event in baseline["analysis"]["motion_events"]]
        if events["baseline"] != expected:
            raise ValueError(f"Production pilot baseline does not reproduce: {ref}; "
                             f"expected {len(expected)}, got {len(events['baseline'])}")
        for name, candidate in events.items():
            if name != "baseline" and _interval_stats(candidate)[1] > 1e-8:
                raise AssertionError(f"Mutually exclusive intervals overlap: {ref} {name}")
        sources[ref] = {"source_sha256": source_hash, "duration_seconds": duration,
                        "sampling": sampling, "raw_samples": samples, "events": events,
                        "metrics": {name: metrics(candidate, duration)
                                    for name, candidate in events.items()},
                        "baseline_reproduced": True}
    return report(sources)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    data = run(args.manifest, args.baseline_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "motion_stabilization.json").write_text(json.dumps(data, indent=2) + "\n")
    (args.output_dir / "motion_stabilization.md").write_text(markdown(data))
    print(json.dumps({name: row["total_events"] for name, row in data["aggregate"].items()}))


if __name__ == "__main__":
    main()
