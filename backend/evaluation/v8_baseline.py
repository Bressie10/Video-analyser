"""Evaluate existing V8 observations against explicitly supplied low-level truth.

Usage: python -m evaluation.v8_baseline path/to/manifest.json
The manifest references local JSON analysis and truth files. No media is fetched or processed.
Absent truth sections are not evaluated; empty truth lists mean exhaustively checked negatives.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _scores(matches: int, predicted: int, expected: int) -> dict:
    return {
        "matched": matches,
        "predicted": predicted,
        "expected": expected,
        "precision": matches / predicted if predicted else None,
        "recall": matches / expected if expected else None,
    }


def _pair(candidates: list[tuple[float, int, int]], predicted: int, expected: int):
    """One-to-one pairing, best quality first, with deterministic index tie breaks."""
    used_pred, used_truth, pairs = set(), set(), []
    for quality, p, t in sorted(candidates, key=lambda row: (-row[0], row[1], row[2])):
        if p not in used_pred and t not in used_truth:
            used_pred.add(p)
            used_truth.add(t)
            pairs.append((p, t))
    return _scores(len(pairs), predicted, expected), pairs


def _interval(row: dict, start: str, end: str) -> tuple[float, float]:
    a, b = float(row[start]), float(row[end])
    if a < 0 or b <= a:
        raise ValueError(f"Invalid interval: {row}")
    return a, b


def _iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return overlap / (max(a[1], b[1]) - min(a[0], b[0])) if overlap else 0.0


def _tokens(value: str) -> list[str]:
    return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)


def _edit_distance(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def evaluate(analysis: dict, truth: dict, *, boundary_tolerance_seconds: float = 0.25,
             minimum_interval_iou: float = 0.5) -> dict:
    """Return independent metrics only for truth sections present in this fixture."""
    if boundary_tolerance_seconds < 0 or not 0 < minimum_interval_iou <= 1:
        raise ValueError("Tolerance must be nonnegative and interval IoU in (0, 1]")
    result = {}
    if "scene_boundaries_seconds" in truth:
        predicted = [float(s["cut_timestamp_seconds"]) for s in analysis["scenes"]
                     if s["cut_timestamp_seconds"] is not None]
        expected = [float(t) for t in truth["scene_boundaries_seconds"]]
        candidates = [(1 / (1 + abs(p - t)), pi, ti) for pi, p in enumerate(predicted)
                      for ti, t in enumerate(expected) if abs(p - t) <= boundary_tolerance_seconds]
        score, pairs = _pair(candidates, len(predicted), len(expected))
        score["mean_absolute_error_seconds"] = (
            sum(abs(predicted[p] - expected[t]) for p, t in pairs) / len(pairs) if pairs else None)
        result["scene_boundaries"] = score

    if "on_screen_text" in truth:
        predicted = analysis["on_screen_text"]
        expected = truth["on_screen_text"]
        p_intervals = [_interval(p, "appearance_timestamp_seconds", "disappearance_timestamp_seconds")
                       for p in predicted]
        t_intervals = [_interval(t, "start_seconds", "end_seconds") for t in expected]
        p_text = [_tokens(p["text"]) for p in predicted]
        t_text = [_tokens(t["text"]) for t in expected]
        text_candidates = [(1.0, pi, ti) for pi, p in enumerate(p_text) for ti, t in enumerate(t_text)
                           if p and p == t]
        text_score, _ = _pair(text_candidates, len(predicted), len(expected))
        candidates = [(overlap, pi, ti) for _, pi, ti in text_candidates
                      if (overlap := _iou(p_intervals[pi], t_intervals[ti])) >= minimum_interval_iou]
        temporal_score, pairs = _pair(candidates, len(predicted), len(expected))
        temporal_score["mean_iou"] = (sum(_iou(p_intervals[p], t_intervals[t]) for p, t in pairs)
                                      / len(pairs) if pairs else None)
        result["ocr"] = {"normalized_text": text_score, "text_and_time": temporal_score}

    if "transcript" in truth:
        predicted = analysis["audio"]
        expected = truth["transcript"]
        p_tokens, t_tokens = _tokens(predicted["text"]), _tokens(expected["text"])
        edits = _edit_distance(t_tokens, p_tokens)
        transcript = {"reference_tokens": len(t_tokens), "hypothesis_tokens": len(p_tokens),
                      "token_errors": edits, "word_error_rate": edits / len(t_tokens) if t_tokens else None}
        if "segments" in expected:
            p_segments, t_segments = predicted["segments"], expected["segments"]
            # Index alignment is meaningful only when the human and model segments correspond.
            if len(p_segments) == len(t_segments) and all(
                _tokens(p["text"]) == _tokens(t["text"]) for p, t in zip(p_segments, t_segments)
            ):
                errors = [abs(float(p[edge]) - float(t[edge])) for p, t in zip(p_segments, t_segments)
                          for edge in ("start", "end")]
                transcript["timestamp_mean_absolute_error_seconds"] = (
                    sum(errors) / len(errors) if errors else None)
                transcript["timestamp_aligned_segments"] = len(t_segments)
            else:
                transcript["timestamp_mean_absolute_error_seconds"] = None
                transcript["timestamp_aligned_segments"] = 0
        result["transcript"] = transcript

    if "motion_events" in truth:
        predicted, expected = analysis["motion_events"], truth["motion_events"]
        p_intervals = [_interval(p, "start_seconds", "end_seconds") for p in predicted]
        t_intervals = [_interval(t, "start_seconds", "end_seconds") for t in expected]
        candidates = [(overlap, pi, ti) for pi, p in enumerate(predicted)
                      for ti, t in enumerate(expected) if p["type"] == t["type"]
                      if (overlap := _iou(p_intervals[pi], t_intervals[ti])) >= minimum_interval_iou]
        score, pairs = _pair(candidates, len(predicted), len(expected))
        score["mean_iou"] = (sum(_iou(p_intervals[p], t_intervals[t]) for p, t in pairs)
                             / len(pairs) if pairs else None)
        result["motion_events"] = score

    if "metadata" in truth:
        checks = {}
        for key, reference in truth["metadata"].items():
            current = analysis["metadata"]
            for part in key.split("."):
                current = current[part]
            if isinstance(reference, dict) and "value" in reference:
                actual, expected = float(current), float(reference["value"])
                tolerance = float(reference.get("tolerance", 0))
                if tolerance < 0:
                    raise ValueError("Metadata tolerance must be nonnegative")
                passed = abs(actual - expected) <= tolerance
                checks[key] = {"actual": actual, "expected": expected, "absolute_error": abs(actual - expected),
                               "within_tolerance": passed}
            else:
                checks[key] = {"actual": current, "expected": reference, "exact_match": current == reference}
        result["metadata"] = checks
    return result


def evaluate_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported baseline manifest schema version")
    fixtures = {}
    for item in manifest["fixtures"]:
        name = item["id"]
        if name in fixtures:
            raise ValueError(f"Duplicate fixture id: {name}")
        # Keep references within the manifest directory; no network or media access.
        def read_local(reference):
            target = (path.parent / reference).resolve()
            if not target.is_relative_to(path.parent.resolve()):
                raise ValueError("Fixture paths must remain in the manifest directory")
            return json.loads(target.read_text())
        fixtures[name] = evaluate(read_local(item["analysis"]), read_local(item["truth"]),
                                  boundary_tolerance_seconds=item.get("boundary_tolerance_seconds", 0.25),
                                  minimum_interval_iou=item.get("minimum_interval_iou", 0.5))
    return {"schema_version": 1, "fixtures": fixtures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_manifest(args.manifest), indent=2, sort_keys=True))
