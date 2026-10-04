"""Offline comparison experiments over validated benchmark documents.

No method in this module is a product score or a provider equivalence claim.
"""

import math
from statistics import median

from intelligence.schemas.benchmark import BenchmarkVideo

MIN_COHORT = 5  # Research gate, not a production confidence threshold.
AGE_TOLERANCE_DAYS = 2  # Research hypothesis, not provider policy.
METHODS = ("account_median", "baseline_ratio", "log_ratio", "percentile",
           "robust_deviation", "age_matched_percentile")
BASELINE_METHODS = ("account_median", "baseline_ratio", "log_ratio")


def source_tokens(video: BenchmarkVideo) -> set[tuple[str, str, str]]:
    """Only exact provider IDs or public URLs establish source identity."""
    source = video.source
    return {(source.platform, kind, value) for kind, value in
            (("provider_id", source.provider_identifier), ("public_url", source.public_url)) if value}


def age_days(video: BenchmarkVideo) -> float | None:
    snap = video.performance
    published = video.publication.published_at
    if snap is None or published is None or snap.observation_window_start != published:
        return None
    if snap.observation_window_end != snap.fetched_at or snap.fetched_at < published:
        return None
    return (snap.fetched_at - published).total_seconds() / 86400


def unknown_context(video: BenchmarkVideo, metric: str) -> list[str]:
    snap = video.performance
    if snap is None:
        return ["performance snapshot absent"]
    if metric not in snap.metric_definitions or snap.metrics.get(metric) is None:
        return ["metric missing or null"]
    missing = []
    if not video.source.platform.strip():
        missing.append("platform")
    if snap.exposure in ("unknown", "mixed"):
        missing.append("exposure unknown or mixed")
    if not video.creator.account_identifier:
        missing.append("account identity")
    if not video.publication.content_type:
        missing.append("content type")
    if age_days(video) is None:
        missing.append("explicit publication-to-fetch observation window")
    return missing


def peer_exclusions(target: BenchmarkVideo, peer: BenchmarkVideo, metric: str) -> list[str]:
    reasons = unknown_context(peer, metric)
    if reasons:
        return reasons
    a, b = target.performance, peer.performance
    for name, left, right in (
        ("platform", target.source.platform, peer.source.platform),
        ("account", target.creator.account_identifier, peer.creator.account_identifier),
        ("exposure", a.exposure, b.exposure),
        ("snapshot source", a.source, b.source),
        ("content type", target.publication.content_type, peer.publication.content_type),
        ("declared format", target.publication.declared_format, peer.publication.declared_format),
        ("attribution context", a.attribution_context, b.attribution_context),
        ("metric definition", a.metric_definitions[metric], b.metric_definitions[metric]),
    ):
        if left != right:
            reasons.append(f"{name} mismatch")
    if abs(age_days(peer) - age_days(target)) > AGE_TOLERANCE_DAYS:
        reasons.append("publication age mismatch")
    return reasons


def deduplicate(videos: list[BenchmarkVideo]) -> tuple[list[BenchmarkVideo], int]:
    """Collapse exact provider-ID/URL aliases; use the latest eligible snapshot."""
    groups: list[tuple[set, list[BenchmarkVideo]]] = []
    for video in videos:
        tokens = source_tokens(video)
        matches = [group for group in groups if group[0] & tokens]
        if not matches:
            groups.append((set(tokens), [video]))
            continue
        combined_tokens, combined = set(tokens), [video]
        for group in matches:
            combined_tokens.update(group[0])
            combined.extend(group[1])
            groups.remove(group)
        groups.append((combined_tokens, combined))
    chosen = [max(rows, key=lambda row: row.performance.fetched_at)
              for _, rows in groups]
    return chosen, len(videos) - len(chosen)


def evaluate(videos: list[BenchmarkVideo], target: BenchmarkVideo, metric: str) -> list[dict]:
    """Return method-specific evidence. The target never enters its own cohort."""
    snap = target.performance
    value = snap.metrics.get(metric) if snap else None
    source = {"platform": target.source.platform, "snapshot_source": snap.source if snap else None,
              "exposure": snap.exposure if snap else None,
              "account_identifier": target.creator.account_identifier,
              "content_type": target.publication.content_type,
              "declared_format": target.publication.declared_format,
              "attribution_context": snap.attribution_context if snap else None,
              "observation_window_start": snap.observation_window_start.isoformat()
              if snap and snap.observation_window_start else None,
              "observation_window_end": snap.observation_window_end.isoformat()
              if snap and snap.observation_window_end else None,
              "publication_age_days": age_days(target),
              "metric_definition": snap.metric_definitions[metric].model_dump()
              if snap and metric in snap.metric_definitions else None}
    base = {"metric": metric, "source_context": source, "target": target.source.reference,
            "comparison_type": "peer_video_cohort", "inputs": {"target_value": value}}

    def result(method, eligible=False, normalized_result=None, reason=None, cohort=None, inputs=None,
               limitations=None, excluded=None, duplicates=0):
        return {**base, "method": method, "normalized_result": normalized_result,
                "eligible": eligible, "reason": reason, "sample_size": len(cohort or []),
                "cohort": [item.source.reference for item in cohort or []],
                "cohort_identity": [item.source.reference for item in cohort or []],
                "comparison_context": {"kind": "peer_video_cohort", "platform": target.source.platform,
                                       "exposure": snap.exposure if snap else None,
                                       "age_tolerance_days": AGE_TOLERANCE_DAYS,
                                       "deduplicated_records": duplicates,
                                       "members": [{"reference": item.source.reference,
                                                    "provider_identifier": item.source.provider_identifier,
                                                    "public_url": item.source.public_url,
                                                    "observation_window_start":
                                                    item.performance.observation_window_start.isoformat(),
                                                    "observation_window_end":
                                                    item.performance.observation_window_end.isoformat(),
                                                    "publication_age_days": age_days(item)}
                                                   for item in cohort or []]},
                "excluded": excluded or [],
                "inputs": {**base["inputs"], **(inputs or {})},
                "limitations": limitations if limitations is not None else []}

    missing = unknown_context(target, metric)
    if missing:
        return [result(method, reason="insufficient target context: " + ", ".join(missing))
                for method in METHODS]

    candidates, excluded = [], []
    target_tokens = source_tokens(target)
    # Include exact provenance aliases reached through another record. A target
    # with provider ID + URL must not re-enter via a URL-only snapshot.
    while True:
        expanded = set(target_tokens)
        for video in videos:
            tokens = source_tokens(video)
            if tokens & target_tokens:
                expanded.update(tokens)
        if expanded == target_tokens:
            break
        target_tokens = expanded
    for video in videos:
        if source_tokens(video) & target_tokens:
            excluded.append({"reference": video.source.reference, "reasons": ["target source"]})
            continue
        reasons = peer_exclusions(target, video, metric)
        if reasons:
            excluded.append({"reference": video.source.reference, "reasons": reasons})
        else:
            candidates.append(video)
    cohort, duplicates = deduplicate(candidates)
    limitations = ["Observational snapshot counts; no causal or quality inference.",
                   "Equal declared metric definitions do not prove provider measurement equivalence.",
                   "Two-day publication-age tolerance is an unvalidated experiment."]
    if target.publication.declared_format is None:
        limitations.append("Declared format is unknown; format comparability was not established.")
    if snap.attribution_context is None:
        limitations.append("Attribution context is unspecified; qualification comparability was not established.")
    if len(cohort) < MIN_COHORT:
        return [result(method, reason=f"insufficient eligible peer cohort (<{MIN_COHORT})",
                       cohort=cohort, limitations=limitations, excluded=excluded, duplicates=duplicates)
                for method in METHODS]

    values = [video.performance.metrics[metric] for video in cohort]
    baseline = median(values)
    common = {"cohort": cohort, "inputs": {"cohort_values": values, "account_median": baseline},
              "limitations": limitations, "excluded": excluded, "duplicates": duplicates}
    output = [result("account_median", True, value - baseline, **common)]
    if baseline > 0:
        output.append(result("baseline_ratio", True, value / baseline, **common))
        output.append(result("log_ratio", True, math.log(value / baseline), **common) if value > 0 else
                      result("log_ratio", reason="log ratio undefined for zero target", **common))
    else:
        output.extend(result(method, reason="zero account median denominator", **common)
                      for method in ("baseline_ratio", "log_ratio"))
    percentile = 100 * (sum(x < value for x in values) + .5 * sum(x == value for x in values)) / len(values)
    output.append(result("percentile", True, percentile, **common))
    mad = median(abs(x - baseline) for x in values)
    output.append(result("robust_deviation", True, (value - baseline) / (1.4826 * mad),
                         inputs={**common["inputs"], "median_absolute_deviation": mad},
                         cohort=cohort, limitations=limitations, excluded=excluded,
                         duplicates=duplicates) if mad > 0 else
                  result("robust_deviation", reason="zero median absolute deviation", **common))
    target_age = age_days(target)
    aged = [video for video in cohort if age_days(video) is not None and target_age is not None
            and abs(age_days(video) - target_age) <= AGE_TOLERANCE_DAYS]
    if len(aged) < MIN_COHORT:
        output.append(result("age_matched_percentile", reason="insufficient age-matched cohort or explicit publication windows",
                             cohort=aged, inputs={"target_age_days": target_age}, limitations=limitations,
                             excluded=excluded, duplicates=duplicates))
    else:
        aged_values = [video.performance.metrics[metric] for video in aged]
        aged_rank = 100 * (sum(x < value for x in aged_values) +
                          .5 * sum(x == value for x in aged_values)) / len(aged_values)
        output.append(result("age_matched_percentile", True, aged_rank, cohort=aged,
                             inputs={"target_age_days": target_age, "cohort_values": aged_values,
                                     "tolerance_days": AGE_TOLERANCE_DAYS}, limitations=limitations,
                             excluded=excluded, duplicates=duplicates))
    return output


def evaluate_baseline(target: BenchmarkVideo, metric: str,
                      declared_context: dict | None) -> list[dict]:
    """Compare with a frozen AccountBaseline using external structured context.

    The baseline's window describes cohort selection. Its method reference must
    explicitly say `median`; no distribution is fabricated from a summary.
    """
    baseline, snap = target.baseline, target.performance
    value = snap.metrics.get(metric) if snap else None
    source = {"platform": target.source.platform,
              "exposure": snap.exposure if snap else None,
              "snapshot_source": snap.source if snap else None,
              "content_type": target.publication.content_type,
              "declared_format": target.publication.declared_format,
              "attribution_context": snap.attribution_context if snap else None,
              "metric_definition": snap.metric_definitions[metric].model_dump()
              if snap and metric in snap.metric_definitions else None,
              "observation_window_start": snap.observation_window_start.isoformat()
              if snap and snap.observation_window_start else None,
              "observation_window_end": snap.observation_window_end.isoformat()
              if snap and snap.observation_window_end else None,
              "publication_age_days": age_days(target)}
    comparison = {"kind": "account_baseline", "baseline_source": baseline.source if baseline else None,
                  "cohort_definition": baseline.cohort_definition if baseline else None,
                  "window_start": baseline.window_start.isoformat() if baseline else None,
                  "window_end": baseline.window_end.isoformat() if baseline else None,
                  "method_reference": baseline.method_reference if baseline else None,
                  "baseline_metric_definition": baseline.metric_definitions[metric].model_dump()
                  if baseline and metric in baseline.metric_definitions else None,
                  "declared_context": declared_context}
    limitations = ["Precomputed cohort membership and distribution cannot be audited from the summary.",
                   "Equal declared definitions do not prove provider measurement equivalence."]
    if target.publication.declared_format is None:
        limitations.append("Declared format is unknown; format comparability was not established.")
    if snap is not None and snap.attribution_context is None:
        limitations.append("Attribution context is unspecified; qualification comparability was not established.")

    def result(method, eligible=False, normalized_result=None, reason=None):
        return {"metric": metric, "comparison_type": "account_baseline", "target": target.source.reference,
                "source_context": source, "comparison_context": comparison, "method": method,
                "eligible": eligible, "normalized_result": normalized_result, "reason": reason,
                "sample_size": baseline.sample_size if baseline else 0,
                "cohort_identity": {"baseline_source": baseline.source,
                                    "cohort_definition": baseline.cohort_definition} if baseline else None,
                "inputs": {"target_value": value, "baseline_value": baseline.metrics.get(metric)
                           if baseline else None}, "limitations": limitations}

    reasons = unknown_context(target, metric)
    if baseline is None:
        reasons.append("account baseline absent")
    elif metric not in baseline.metric_definitions or baseline.metrics.get(metric) is None:
        reasons.append("baseline metric missing or null")
    else:
        if snap and baseline.metric_definitions[metric] != snap.metric_definitions[metric]:
            reasons.append("metric definition mismatch")
        if baseline.method_reference != "median":
            reasons.append("baseline method is not declared median")
        if baseline.sample_size < MIN_COHORT:
            reasons.append(f"insufficient baseline sample (<{MIN_COHORT})")

    required = ("platform", "account_identifier", "exposure", "snapshot_source", "content_type", "declared_format",
                "attribution_context", "observation_window_basis", "publication_age_min_days",
                "publication_age_max_days", "target_excluded")
    if declared_context is None or any(key not in declared_context for key in required):
        reasons.append("structured baseline comparison context unavailable")
    else:
        expected = {"platform": target.source.platform,
                    "account_identifier": target.creator.account_identifier,
                    "exposure": snap.exposure if snap else None,
                    "snapshot_source": snap.source if snap else None,
                    "content_type": target.publication.content_type,
                    "declared_format": target.publication.declared_format,
                    "attribution_context": snap.attribution_context if snap else None,
                    "observation_window_basis": "publication_to_fetch"}
        for key, actual in expected.items():
            declared = declared_context[key]
            if declared is None and key not in ("declared_format", "attribution_context"):
                reasons.append(f"baseline {key} unknown")
            elif isinstance(declared, str) and not declared.strip():
                reasons.append(f"baseline {key} unknown")
            elif declared != actual:
                reasons.append(f"baseline {key} mismatch")
        low, high = declared_context["publication_age_min_days"], declared_context["publication_age_max_days"]
        if (not isinstance(low, (int, float)) or not isinstance(high, (int, float))
                or isinstance(low, bool) or isinstance(high, bool) or low < 0 or high < low):
            reasons.append("baseline publication age context unknown or invalid")
        elif age_days(target) is not None and not low <= age_days(target) <= high:
            reasons.append("publication age mismatch")
        if declared_context["target_excluded"] is not True:
            reasons.append("target exclusion from baseline unverified")
    if reasons:
        return [result(method, reason="; ".join(reasons)) for method in BASELINE_METHODS]
    median_value = baseline.metrics[metric]
    output = [result("account_median", True, value - median_value)]
    output.append(result("baseline_ratio", True, value / median_value) if median_value > 0 else
                  result("baseline_ratio", reason="zero account median denominator"))
    output.append(result("log_ratio", True, math.log(value / median_value))
                  if median_value > 0 and value > 0 else
                  result("log_ratio", reason="log ratio undefined for zero target or median"))
    return output
