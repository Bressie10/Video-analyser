"""Offline V9 Stage 1 pilot: private manifest, unchanged V8 runner, signal evaluation.

Run with ``python -m intelligence.evaluation.stage1 {validate,run,evaluate} ...``.
This module is deliberately outside the production app import graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from .v8_baseline import _edit_distance, _interval, _iou, _tokens


SIGNALS = ("scene_boundaries", "ocr", "transcript", "motion", "metadata")
MOTION_TYPES = {"camera_shake", "camera_zoom", "camera_pan", "general_motion",
                "local_motion", "unknown"}
VARIATION = {"talking_head", "tutorial", "product_demo", "screen_recording",
             "interview", "storytime", "before_after", "fast_editing", "slow_editing",
             "captions", "no_captions", "music", "no_music", "clean_audio",
             "noisy_audio", "simple_scene", "busy_scene", "weak", "ordinary", "strong"}
REPO = Path(__file__).resolve().parents[3]


def _private_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(REPO):
        raise ValueError(f"Private media, truth and results must be outside Git: {path}")
    return path


def load_manifest(path: Path, *, pilot_size: bool = True) -> dict:
    """Validate a private pilot manifest; never open or download media here."""
    path = _private_path(path)
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), list):
        raise ValueError("Stage 1 manifest needs schema_version 1 and sources")
    sources = manifest["sources"]
    if pilot_size and not 10 <= len(sources) <= 15:
        raise ValueError("Pilot needs 10 to 15 sources")
    refs, media, groups, creators, creator_groups = set(), set(), {}, Counter(), {}
    for item in sources:
        required = {"source_ref", "media_path", "duration_seconds", "creator_ref", "rights_note",
                    "annotation_status", "partition", "group_ref", "low_level_truth_available",
                    "variation"}
        if not required <= set(item):
            raise ValueError(f"Missing source fields: {sorted(required - set(item))}")
        ref = item["source_ref"]
        if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", ref) or ref in refs:
            raise ValueError("Source references must be unique safe identifiers")
        refs.add(ref)
        media_path = _private_path(Path(item["media_path"]))
        if not Path(item["media_path"]).expanduser().is_absolute() or media_path in media:
            raise ValueError("Media paths must be unique absolute private paths")
        media.add(media_path)
        if not isinstance(item["duration_seconds"], (int, float)) or not math.isfinite(item["duration_seconds"]) or item["duration_seconds"] <= 0:
            raise ValueError(f"Invalid duration for {ref}")
        if not isinstance(item["rights_note"], str) or not item["rights_note"].strip():
            raise ValueError(f"Rights/provenance note required for {ref}")
        if item["annotation_status"] not in {"pending", "first_pass", "two_independent", "adjudicated", "reviewed"}:
            raise ValueError(f"Invalid annotation status for {ref}")
        if item["partition"] not in {"train", "validation", "test"}:
            raise ValueError(f"Invalid partition for {ref}")
        group = item["group_ref"]
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"Nonblank group_ref required for {ref}")
        if group in groups and groups[group] != item["partition"]:
            raise ValueError("A source group cannot cross partitions")
        groups[group] = item["partition"]
        creator = item["creator_ref"]
        if creator is not None:
            if not isinstance(creator, str) or not creator.strip():
                raise ValueError(f"Invalid creator_ref for {ref}")
            creators[creator] += 1
            if creator in creator_groups and creator_groups[creator] != group:
                raise ValueError("A known creator must stay in one source group")
            creator_groups[creator] = group
        if not isinstance(item["low_level_truth_available"], bool):
            raise ValueError(f"low_level_truth_available must be boolean for {ref}")
        if not isinstance(item["variation"], list) or not set(item["variation"]) <= VARIATION:
            raise ValueError(f"Invalid variation tags for {ref}")
    if pilot_size and (len(groups) < 5 or any(count > 3 for count in creators.values())):
        raise ValueError("Pilot needs at least five source groups and at most three clips per known creator")
    return manifest


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(manifest_path: Path, output_dir: Path, *, analyzer=None) -> dict:
    """Run the existing shared analysis pipeline, one private JSON result per source."""
    manifest = load_manifest(manifest_path)
    output_dir = _private_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if analyzer is None:
        from app.analysis_pipeline import analyze_file
        analyzer = analyze_file
    from subprocess import check_output
    version = check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    results = {}
    for item in manifest["sources"]:
        source = Path(item["media_path"]).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = output_dir / f"{item['source_ref']}.json"
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite analysis: {target}")
        with tempfile.TemporaryDirectory(prefix="cm-stage1-") as work:
            analysis = analyzer(source, work, allow_silent=True)
        payload = {"source_ref": item["source_ref"], "pipeline_version": version,
                   "input_sha256": _hash(source), "analysis": analysis}
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        results[item["source_ref"]] = str(target)
    return results


def _counts(matched: int, predicted: int, expected: int) -> dict:
    precision = matched / predicted if predicted else None
    recall = matched / expected if expected else None
    return {"tp": matched, "fp": predicted - matched, "fn": expected - matched,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None}


def _pair(candidates, n_pred, n_truth):
    """Deterministic maximum-cardinality one-to-one assignment for small pilots."""
    # An augmenting path prevents a locally best edge from reducing recall.
    edges = [[] for _ in range(n_pred)]
    for quality, p, t in sorted(candidates, key=lambda x: (-x[0], x[1], x[2])):
        edges[p].append(t)
    owner = {}

    def assign(p, seen):
        for t in edges[p]:
            if t in seen:
                continue
            seen.add(t)
            if t not in owner or assign(owner[t], seen):
                owner[t] = p
                return True
        return False

    for p in range(n_pred):
        assign(p, set())
    return sorted((p, t) for t, p in owner.items())


def _score_scene(predicted, truth, tolerances):
    p = [float(x["cut_timestamp_seconds"]) for x in predicted if x.get("cut_timestamp_seconds") is not None]
    t = [float(x["time_seconds"]) for x in truth]
    rows = {}
    for tolerance in tolerances:
        pairs = _pair([(1 / (1 + abs(a - b)), i, j) for i, a in enumerate(p)
                       for j, b in enumerate(t) if abs(a - b) <= tolerance], len(p), len(t))
        errors = [round(abs(p[i] - t[j]), 4) for i, j in pairs]
        rows[str(tolerance)] = _counts(len(pairs), len(p), len(t)) | {
            "mean_timing_error_seconds": sum(errors) / len(errors) if errors else None,
            "timing_errors_seconds": errors,
            "unmatched_prediction_seconds": [p[i] for i in range(len(p)) if i not in {a for a, _ in pairs}],
            "unmatched_truth_seconds": [t[j] for j in range(len(t)) if j not in {b for _, b in pairs}]}
    return rows


def _score_ocr(predicted, truth, min_iou):
    p = [_interval(x, "appearance_timestamp_seconds", "disappearance_timestamp_seconds") for x in predicted]
    t = [_interval(x, "start_seconds", "end_seconds") for x in truth]
    candidates = []
    for i, row in enumerate(predicted):
        for j, gold in enumerate(truth):
            overlap = _iou(p[i], t[j])
            if overlap:
                a = _tokens(row["text"])
                b = _tokens(gold["normalized_text"])
                similarity = 1 - _edit_distance(a, b) / max(len(a), len(b), 1)
                candidates.append((overlap + similarity, i, j))
    pairs = _pair(candidates, len(p), len(t))
    exact = [(i, j) for i, j in pairs if _tokens(predicted[i]["text"]) == _tokens(truth[j]["normalized_text"])]
    timed = [(i, j) for i, j in exact if _iou(p[i], t[j]) >= min_iou]
    similarities = [1 - _edit_distance(_tokens(predicted[i]["text"]), _tokens(truth[j]["normalized_text"])) /
                    max(len(_tokens(predicted[i]["text"])), len(_tokens(truth[j]["normalized_text"])), 1)
                    for i, j in pairs]
    return {"exact_text": _counts(len(exact), len(p), len(t)),
            "exact_text_and_time": _counts(len(timed), len(p), len(t)),
            "normalized_text_similarity_mean": sum(similarities) / len(similarities) if similarities else None,
            "temporal_iou_mean": sum(_iou(p[i], t[j]) for i, j in pairs) / len(pairs) if pairs else None,
            "missed_visible_text_rate": (len(t) - len(pairs)) / len(t) if t else None,
            "unmatched_truth_indices": [j for j in range(len(t)) if j not in {b for _, b in pairs}],
            "unmatched_prediction_indices": [i for i in range(len(p)) if i not in {a for a, _ in pairs}]}


def _score_transcript(predicted, truth):
    reference = _tokens(truth["text"])
    hypothesis = _tokens(predicted["text"])
    segments = truth.get("segments", [])
    p_segments = predicted.get("segments", [])
    p_intervals = [_interval(x, "start", "end") for x in p_segments]
    t_intervals = [_interval(x, "start", "end") for x in segments]
    pairs = _pair([(_iou(a, b), i, j) for i, a in enumerate(p_intervals)
                   for j, b in enumerate(t_intervals) if _iou(a, b) > 0], len(p_intervals), len(t_intervals))
    # Timing is valid only when both segment text and its temporal correspondence match.
    aligned = [(i, j) for i, j in pairs if _tokens(p_segments[i]["text"]) == _tokens(segments[j]["text"])]
    errors = [abs(p_intervals[i][edge] - t_intervals[j][edge]) for i, j in aligned for edge in (0, 1)]
    edits = _edit_distance(reference, hypothesis)
    return {"reference_tokens": len(reference), "hypothesis_tokens": len(hypothesis),
            "token_errors": edits, "word_error_rate": edits / len(reference) if reference else None,
            "segment_timing_mean_error_seconds": sum(errors) / len(errors) if errors else None,
            "timing_aligned_segments": len(aligned),
            "missing_speech_segments": len(t_intervals) - len(pairs) if "segments" in truth else None,
            "hallucinated_speech_segments": len(p_intervals) - len(pairs) if "segments" in truth else None,
            "segment_overlap_comparison_available": "segments" in truth}


def _score_motion(predicted, truth, min_iou):
    p = [_interval(x, "start_seconds", "end_seconds") for x in predicted]
    t = [_interval(x, "start_seconds", "end_seconds") for x in truth]
    candidates = [(_iou(a, b), i, j) for i, a in enumerate(p) for j, b in enumerate(t)
                  if _iou(a, b) >= min_iou]
    pairs = _pair(candidates, len(p), len(t))
    confusion = Counter((truth[j]["type"], predicted[i]["type"]) for i, j in pairs)
    same = sum(1 for i, j in pairs if predicted[i]["type"] == truth[j]["type"])
    return {"presence_overlap": _counts(len(pairs), len(p), len(t)),
            "type_correct": same, "type_confusion": [
                {"truth": a, "predicted": b, "count": n} for (a, b), n in sorted(confusion.items())],
            "temporal_iou_mean": sum(_iou(p[i], t[j]) for i, j in pairs) / len(pairs) if pairs else None,
            "unmatched_truth_indices": [j for j in range(len(t)) if j not in {b for _, b in pairs}],
            "unmatched_prediction_indices": [i for i in range(len(p)) if i not in {a for a, _ in pairs}]}


def _score_metadata(predicted, truth):
    rows = {}
    for key, reference in sorted(truth.items()):
        value = predicted
        for part in key.split("."):
            value = value[part]
        expected = reference["value"]
        tolerance = reference.get("tolerance", 0)
        if tolerance < 0:
            raise ValueError("Negative metadata tolerance")
        rows[key] = {"actual": value, "expected": expected, "tolerance": tolerance,
                     "correct": isinstance(value, (int, float)) and
                                isinstance(expected, (int, float)) and
                                math.isfinite(value) and math.isfinite(expected) and
                                abs(value - expected) <= tolerance}
    return rows


def evaluate_one(analysis: dict, truth: dict, *, tolerances=(0.1, 0.25, 0.5), min_iou=0.5) -> dict:
    """Evaluate only fully reviewed signal truth; partial coverage is an abstention."""
    coverage = truth["coverage"]
    if set(coverage) != set(SIGNALS) or any(value not in {"complete", "partial", "unavailable"} for value in coverage.values()):
        raise ValueError("Explicit complete/partial/unavailable coverage needed for every signal")
    results = {}
    for signal in SIGNALS:
        if coverage[signal] != "complete":
            results[signal] = {"status": "abstained", "reason": coverage[signal]}
            continue
        if signal not in truth:
            raise ValueError(f"Complete truth section missing: {signal}")
        value = truth[signal]
        if signal == "scene_boundaries":
            result = _score_scene(analysis["scenes"], value, tolerances)
        elif signal == "ocr":
            result = _score_ocr(analysis["on_screen_text"], value, min_iou)
        elif signal == "transcript":
            result = _score_transcript(analysis["audio"], value)
        elif signal == "motion":
            if any(row["type"] not in MOTION_TYPES for row in value):
                raise ValueError("Motion truth type must map to an existing V8 output type")
            result = _score_motion(analysis["motion_events"], value, min_iou)
        else:
            result = _score_metadata(analysis["metadata"], value)
        results[signal] = {"status": "measured", "result": result}
    return results


def validate_truth(truth: dict, duration_seconds: float) -> None:
    """Reject impossible reviewed timings before measuring the existing pipeline."""
    coverage = truth.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != set(SIGNALS):
        raise ValueError("Every low-level signal needs explicit coverage")
    for signal, status in coverage.items():
        if status not in {"complete", "partial", "unavailable"}:
            raise ValueError(f"Invalid low-level coverage: {signal}")
        if status == "complete" and signal not in truth:
            raise ValueError(f"Complete truth section missing: {signal}")
    if coverage["scene_boundaries"] == "complete":
        times = [row["time_seconds"] for row in truth["scene_boundaries"]]
        if any(not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 < t < duration_seconds for t in times):
            raise ValueError("Editorial boundaries must be within the source duration")
        if times != sorted(set(times)):
            raise ValueError("Editorial boundaries must be unique and in time order")
    for signal, start, end in (("ocr", "start_seconds", "end_seconds"),
                               ("motion", "start_seconds", "end_seconds")):
        if coverage[signal] != "complete":
            continue
        for row in truth[signal]:
            a, b = _interval(row, start, end)
            if not math.isfinite(a) or not math.isfinite(b) or b > duration_seconds:
                raise ValueError(f"{signal} interval exceeds source duration")
            if signal == "ocr" and (not row.get("text") or not row.get("normalized_text")):
                raise ValueError("Visible OCR text needs literal and normalized text")
            if signal == "motion" and row["type"] not in MOTION_TYPES:
                raise ValueError("Motion truth must map to a V8 output type")
    if coverage["transcript"] == "complete":
        if not isinstance(truth["transcript"].get("text"), str):
            raise ValueError("Human transcript text is required")
        for segment in truth["transcript"].get("segments", []):
            a, b = _interval(segment, "start", "end")
            if not math.isfinite(a) or not math.isfinite(b) or b > duration_seconds:
                raise ValueError("Transcript segment exceeds source duration")
    if coverage["metadata"] == "complete":
        for field, row in truth["metadata"].items():
            if field not in {"duration_seconds", "video.resolution.width", "video.resolution.height", "video.fps"}:
                raise ValueError(f"Unsupported independent metadata field: {field}")
            if not isinstance(row.get("value"), (int, float)) or not math.isfinite(row["value"]) or row.get("tolerance", 0) < 0:
                raise ValueError(f"Invalid metadata truth: {field}")


def annotation_audit(manifest_path: Path, semantic_dir: Path, reviewed_dir: Path) -> dict:
    """Check two independent frozen-contract records before a reviewed third record."""
    from intelligence.schemas.annotation import Annotation
    from .agreement import compare_all
    from .dataset import load_dataset

    manifest = load_manifest(manifest_path)
    semantic_dir, reviewed_dir = _private_path(semantic_dir), _private_path(reviewed_dir)
    dataset, _ = load_dataset(semantic_dir)
    expected = {item["source_ref"]: item for item in manifest["sources"]}
    by_source = {ref: [] for ref in expected}
    for record in dataset.annotations:
        ref = record.source.reference_id
        if ref not in expected:
            raise ValueError(f"Unknown semantic source: {ref}")
        by_source[ref].append(record)
    if {item.source_ref: (item.partition, item.group_ref) for item in dataset.split_assignments} != {
            ref: (item["partition"], item["group_ref"]) for ref, item in expected.items()}:
        raise ValueError("Semantic dataset splits/groups must match pilot manifest")
    rows = {}
    for ref, records in by_source.items():
        if len(records) != 2 or len({r.annotator_ref for r in records}) != 2:
            raise ValueError(f"Two distinct independent annotations required: {ref}")
        if any(r.guideline_version != "1.1.0" for r in records):
            raise ValueError(f"Guideline 1.1.0 required: {ref}")
        if any(r.source.duration_seconds != expected[ref]["duration_seconds"] for r in records):
            raise ValueError(f"Annotation duration differs from manifest: {ref}")
        reviewed_path = reviewed_dir / f"{ref}.json"
        notes_path = reviewed_dir / f"{ref}.md"
        reviewed = None
        if reviewed_path.exists():
            reviewed = Annotation.model_validate_json(reviewed_path.read_text())
            if reviewed.source != records[0].source or reviewed.annotator_ref in {r.annotator_ref for r in records}:
                raise ValueError(f"Reviewed truth needs same source and a separate reviewer: {ref}")
            if reviewed.guideline_version != "1.1.0" or not notes_path.exists() or not notes_path.read_text().strip():
                raise ValueError(f"Reviewed truth needs guideline 1.1.0 and adjudication notes: {ref}")
        if expected[ref]["annotation_status"] == "reviewed" and reviewed is None:
            raise ValueError(f"Manifest marks reviewed without reviewed record: {ref}")
        rows[ref] = {"independent_annotators": sorted(r.annotator_ref for r in records),
                     "reviewed": reviewed is not None,
                     "coverage": [r.coverage.model_dump() for r in records]}
    return {"sources": rows, "agreement": compare_all(dataset.annotations)}


def evaluate_pilot(manifest_path: Path, results_dir: Path, truth_dir: Path,
                   *, scene_tolerances=(0.1, 0.25, 0.5)) -> dict:
    if not scene_tolerances or any(not math.isfinite(t) or t < 0 for t in scene_tolerances):
        raise ValueError("Scene tolerances must be finite nonnegative seconds")
    if len(set(scene_tolerances)) != len(scene_tolerances):
        raise ValueError("Scene tolerances must be unique")
    manifest = load_manifest(manifest_path)
    results_dir, truth_dir = _private_path(results_dir), _private_path(truth_dir)
    rows = {}
    hashes = set()
    for item in manifest["sources"]:
        ref = item["source_ref"]
        result_path, truth_path = results_dir / f"{ref}.json", truth_dir / f"{ref}.json"
        if not item["low_level_truth_available"] or not truth_path.exists() or not result_path.exists():
            rows[ref] = {"status": "missing_data", "truth_available": truth_path.exists(),
                         "analysis_available": result_path.exists()}
            continue
        payload = json.loads(result_path.read_text())
        truth = json.loads(truth_path.read_text())
        if payload["source_ref"] != ref or truth["source_ref"] != ref:
            raise ValueError(f"Source reference mismatch: {ref}")
        validate_truth(truth, item["duration_seconds"])
        if payload["input_sha256"] in hashes:
            raise ValueError("Duplicate input hash in pilot")
        hashes.add(payload["input_sha256"])
        rows[ref] = {"status": "evaluated", "pipeline_version": payload["pipeline_version"],
                     "signals": evaluate_one(payload["analysis"], truth, tolerances=scene_tolerances)}
    coverage = {signal: dict(sorted(Counter(
        row["signals"][signal]["status"] if row["status"] == "evaluated" else "missing_data"
        for row in rows.values()).items())) for signal in SIGNALS}
    return {"schema_version": 1, "sources": rows, "coverage": coverage,
            "aggregate": aggregate(rows, scene_tolerances)}


def _wilson(successes: int, trials: int) -> list[float] | None:
    """95% Wilson interval for an observed event proportion; no interval for 0 trials."""
    if not trials:
        return None
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)) / denominator
    return [max(0, centre - radius), min(1, centre + radius)]


def _aggregate_counts(values):
    tp = sum(value["tp"] for value in values)
    fp = sum(value["fp"] for value in values)
    fn = sum(value["fn"] for value in values)
    row = _counts(tp, tp + fp, tp + fn)
    row["precision_wilson_95"] = _wilson(tp, tp + fp)
    row["recall_wilson_95"] = _wilson(tp, tp + fn)
    return row


def aggregate(rows: dict, scene_tolerances=(0.1, 0.25, 0.5)) -> dict:
    """Micro counts by signal. Source results retain timing and failure examples."""
    measured = {signal: [row["signals"][signal]["result"] for row in rows.values()
                         if row["status"] == "evaluated" and row["signals"][signal]["status"] == "measured"]
                for signal in SIGNALS}
    scenes = {str(tolerance): _aggregate_counts([r[str(tolerance)] for r in measured["scene_boundaries"]])
              for tolerance in scene_tolerances}
    ocr = {key: _aggregate_counts([r[key] for r in measured["ocr"]])
           for key in ("exact_text", "exact_text_and_time")}
    motion = _aggregate_counts([r["presence_overlap"] for r in measured["motion"]])
    transcript = {"reference_tokens": sum(r["reference_tokens"] for r in measured["transcript"]),
                  "token_errors": sum(r["token_errors"] for r in measured["transcript"]),
                  "missing_speech_segments": sum(r["missing_speech_segments"] or 0 for r in measured["transcript"]),
                  "hallucinated_speech_segments": sum(r["hallucinated_speech_segments"] or 0 for r in measured["transcript"])}
    transcript["word_error_rate"] = (transcript["token_errors"] / transcript["reference_tokens"]
                                      if transcript["reference_tokens"] else None)
    metadata = {}
    for row in measured["metadata"]:
        for field, check in row.items():
            metadata.setdefault(field, {"correct": 0, "checked": 0})
            metadata[field]["checked"] += 1
            metadata[field]["correct"] += check["correct"]
    for check in metadata.values():
        check["correctness_wilson_95"] = _wilson(check["correct"], check["checked"])
    return {"scene_boundaries": scenes, "ocr": ocr, "transcript": transcript,
            "motion": motion, "metadata": dict(sorted(metadata.items()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "annotations", "run", "evaluate"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--semantic", type=Path)
    parser.add_argument("--reviewed", type=Path)
    parser.add_argument("--scene-tolerances", type=float, nargs="+", default=[0.1, 0.25, 0.5],
                        metavar="SECONDS")
    args = parser.parse_args(argv)
    if args.command == "validate":
        result = {"valid": True, "sources": len(load_manifest(args.manifest)["sources"])}
    elif args.command == "annotations":
        if args.semantic is None or args.reviewed is None:
            parser.error("annotations requires --semantic and --reviewed")
        result = annotation_audit(args.manifest, args.semantic, args.reviewed)
    elif args.command == "run":
        if args.results is None:
            parser.error("run requires --results")
        result = run(args.manifest, args.results)
    else:
        if args.results is None or args.truth is None:
            parser.error("evaluate requires --results and --truth")
        result = evaluate_pilot(args.manifest, args.results, args.truth,
                                scene_tolerances=args.scene_tolerances)
    print(json.dumps(result, indent=2, sort_keys=True, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
