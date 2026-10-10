"""Offline scene-only threshold sweep against provisional reviewed pilot references."""

from __future__ import annotations

import argparse
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

from .stage1 import _counts, _hash, _private_path, _score_scene, load_manifest
from .stage1_truth import validate_record

THRESHOLDS = (20, 24, 27, 30, 33, 36, 40, 45)
TOLERANCES = (0.1, 0.25, 0.5)
BASELINE = 27
SIGNALS = ("scene_boundaries", "ocr", "transcript", "motion", "metadata")


def _detect(path: Path, threshold: int) -> list[dict]:
    from scenedetect import ContentDetector, detect

    scenes = detect(str(path), ContentDetector(threshold=float(threshold)), show_progress=False)
    return [{"cut_timestamp_seconds": round(start.get_seconds(), 3)}
            for start, _ in scenes[1:]]


def _summary(rows: list[dict]) -> dict:
    tp = sum(row["tp"] for row in rows)
    fp = sum(row["fp"] for row in rows)
    fn = sum(row["fn"] for row in rows)
    errors = [error for row in rows for error in row["timing_errors_seconds"]]
    return _counts(tp, tp + fp, tp + fn) | {
        "mean_matched_timing_error_seconds": sum(errors) / len(errors) if errors else None,
        "predicted_cuts": tp + fp,
    }


def evaluate(manifest_path: Path, truth_dir: Path, baseline_dir: Path, *,
             normalise=None, detector=None) -> dict:
    """Run only normalisation and scene detection; fail if baseline drifts."""
    manifest = load_manifest(manifest_path)
    truth_dir, baseline_dir = _private_path(truth_dir), _private_path(baseline_dir)
    if normalise is None:
        from app.video_processing import normalise_video
        normalise = normalise_video
    detector = detector or _detect
    sources = {}
    for item in manifest["sources"]:
        ref = item["source_ref"]
        source = _private_path(Path(item["media_path"]))
        if not source.is_file():
            raise FileNotFoundError(source)
        truth = json.loads((truth_dir / f"{ref}.json").read_text())
        if truth["source_ref"] != ref or truth["coverage"]["scene_boundaries"] != "complete":
            raise ValueError(f"Complete provisional scene reference required: {ref}")
        scene_only_truth = {**truth,
                            "coverage": {signal: ("complete" if signal == "scene_boundaries" else "unavailable")
                                         for signal in SIGNALS},
                            "observations": {"scene_boundaries": truth["observations"]["scene_boundaries"]}}
        validate_record(scene_only_truth, item["duration_seconds"], kind="reviewed")
        baseline = json.loads((baseline_dir / f"{ref}.json").read_text())
        if baseline["source_ref"] != ref or baseline["input_sha256"] != _hash(source):
            raise ValueError(f"Baseline source identity mismatch: {ref}")
        expected_cuts = [row["cut_timestamp_seconds"] for row in baseline["analysis"]["scenes"]
                         if row["cut_timestamp_seconds"] is not None]
        with tempfile.TemporaryDirectory(prefix="cm-stage3-scenes-") as work:
            normalized = Path(work) / "normalised.mp4"
            normalise(source, normalized)
            predictions = {str(t): detector(normalized, t) for t in THRESHOLDS}
        actual_cuts = [row["cut_timestamp_seconds"] for row in predictions[str(BASELINE)]]
        if actual_cuts != expected_cuts:
            raise ValueError(f"Threshold 27 does not reproduce the pilot baseline: {ref}")
        reference = truth["observations"]["scene_boundaries"]
        sources[ref] = {
            "source_sha256": baseline["input_sha256"],
            "reference_cuts": len(reference),
            "thresholds": {str(t): {
                "predicted_cuts": len(predictions[str(t)]),
                "scores": _score_scene(predictions[str(t)], reference, TOLERANCES),
            } for t in THRESHOLDS},
        }
    aggregates = {str(t): {str(tol): _summary([
        source["thresholds"][str(t)]["scores"][str(tol)] for source in sources.values()
    ]) for tol in TOLERANCES} for t in THRESHOLDS}
    ranking = sorted(THRESHOLDS, key=lambda t: (
        -(aggregates[str(t)]["0.5"]["f1"] or 0), t))
    return {
        "schema_version": 1,
        "reference_status": "provisional Gemini + human-checked calibration truth; not production ground truth",
        "scope": "11-video pilot only; no population accuracy claim",
        "detector": {
            "package": "scenedetect", "version": version("scenedetect"),
            "class": "scenedetect.detectors.ContentDetector",
            "call": "scenedetect.detect(video_path, ContentDetector(threshold=...), show_progress=False)",
            "thresholds": list(THRESHOLDS),
            "fixed_settings": {"min_scene_len_frames": 15, "delta_hue": 1.0,
                               "delta_sat": 1.0, "delta_lum": 1.0, "delta_edges": 0.0,
                               "luma_only": False, "kernel_size": None,
                               "filter_mode": "MERGE", "backend": "opencv",
                               "start_in_scene": False},
            "preprocessing": "app.video_processing.normalise_video; one pass per source",
        },
        "baseline_threshold": BASELINE,
        "tolerances_seconds": list(TOLERANCES),
        "sources": sources,
        "aggregate": aggregates,
        "ranked_thresholds_by_0.5s_f1": ranking,
    }


def markdown(report: dict) -> str:
    def metric(value):
        return "—" if value is None else f"{value:.3f}"

    baseline = report["aggregate"][str(BASELINE)]["0.5"]
    leading_threshold = report["ranked_thresholds_by_0.5s_f1"][0]
    leading = report["aggregate"][str(leading_threshold)]["0.5"]
    gain = (f", a small {leading['f1'] - baseline['f1']:.3f} gain"
            if leading["f1"] is not None and baseline["f1"] is not None else "")
    lines = ["# V9 Stage 3 scene threshold sweep", "",
             "Provisional Gemini + human-checked calibration references for 11 pilot videos. "
             "These are not production ground truth; no population accuracy is inferred.", "",
             "Detector: `scenedetect.detectors.ContentDetector`, PySceneDetect "
             f"`{report['detector']['version']}`. Threshold 27 is the unchanged production baseline. "
             "All other settings use the recorded defaults in JSON. Each video was normalised once "
             "with the production preprocessing function; only scene detection was run.", "",
             "## Interpretation", "",
             f"Threshold {leading_threshold} leads at ±0.5 s F1 ({metric(leading['f1'])} versus "
             f"{metric(baseline['f1'])} at 27){gain}. "
             f"It yields {baseline['predicted_cuts'] - leading['predicted_cuts']} fewer predicted cuts and "
             f"{baseline['tp'] - leading['tp']} fewer matched boundaries. "
             "The sweep supports some sensitivity concerns, but does not establish a material "
             "overall gain from changing only the threshold.", "",
             "Videos 04 and 07 still have many false positives at the leading threshold, "
             "and video 09 still has false detections despite zero reference boundaries. "
             "Video 03 remains strong. Higher thresholds reduce some false positives while "
             "also losing true matches; no production threshold is selected here.", "",
             "## Aggregate (ranked by ±0.5 s F1)", "",
             "| Threshold | TP | FP | FN | Precision | Recall | F1 | Mean matched error (s) | Predicted cuts |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for t in report["ranked_thresholds_by_0.5s_f1"]:
        row = report["aggregate"][str(t)]["0.5"]
        lines.append(f"| {t}{' (baseline)' if t == BASELINE else ''} | {row['tp']} | {row['fp']} | {row['fn']} | {metric(row['precision'])} | {metric(row['recall'])} | {metric(row['f1'])} | {metric(row['mean_matched_timing_error_seconds'])} | {row['predicted_cuts']} |")
    for tol in TOLERANCES[:2]:
        lines.extend(["", f"## Aggregate at ±{tol} s", "",
                      "| Threshold | TP | FP | FN | Precision | Recall | F1 | Mean matched error (s) | Predicted cuts |",
                      "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for t in report["ranked_thresholds_by_0.5s_f1"]:
            row = report["aggregate"][str(t)][str(tol)]
            lines.append(f"| {t} | {row['tp']} | {row['fp']} | {row['fn']} | {metric(row['precision'])} | {metric(row['recall'])} | {metric(row['f1'])} | {metric(row['mean_matched_timing_error_seconds'])} | {row['predicted_cuts']} |")
    lines.extend(["", "## Per-video at ±0.5 s", "",
                  "Video 09 has zero reference boundaries. Its recall and F1 are undefined; "
                  "predicted cuts remain visible as false positives.", "",
                  "| Video | Reference cuts | " + " | ".join(f"{t}: P / R / F1 / cuts" for t in THRESHOLDS) + " |",
                  "| --- | ---: | " + " | ".join("---" for _ in THRESHOLDS) + " |"])
    for ref, source in report["sources"].items():
        cells = []
        for t in THRESHOLDS:
            result = source["thresholds"][str(t)]
            row = result["scores"]["0.5"]
            cells.append(" / ".join([metric(row["precision"]), metric(row["recall"]),
                                     metric(row["f1"]), str(result["predicted_cuts"])]))
        lines.append(f"| **{ref}** | {source['reference_cuts']} | " + " | ".join(cells) + " |")
    lines.extend(["", "The JSON contains every video's scores at ±0.1, ±0.25, and ±0.5 s, "
                  "including unmatched timestamps. Ranking is descriptive; precision, recall, "
                  "and videos 03, 04, 07, and 09 should guide any later decision.", "",
                  "## Reproduce", "",
                  "Run `python -m intelligence.evaluation.stage3_scene --manifest MANIFEST "
                  "--truth-dir PROVISIONAL_REVIEWED --baseline-dir PILOT_RESULTS "
                  "--json OUTPUT.json --markdown OUTPUT.md` from `backend` using an environment "
                  "with PySceneDetect and FFmpeg. The private manifest, media, reference files, "
                  "and baseline analysis files are inputs; the command runs normalisation and "
                  "scene detection only.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--truth-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate(args.manifest, args.truth_dir, args.baseline_dir)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(markdown(report))


if __name__ == "__main__":
    main()
