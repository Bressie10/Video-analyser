"""Offline comparison experiments over validated benchmark documents.

No method in this module is a product score or a provider equivalence claim.
"""

import math
from statistics import median

from intelligence.schemas.benchmark import BenchmarkVideo

MIN_COHORT = 5  # Research gate, not a production confidence threshold.
METHODS = ("account_median", "baseline_ratio", "log_ratio", "percentile",
           "robust_deviation", "age_matched_percentile")


def source_key(video: BenchmarkVideo) -> tuple[str, str]:
    source = video.source
    return (source.platform, source.provider_identifier or source.public_url or source.reference)


def context(video: BenchmarkVideo, metric: str) -> tuple | None:
    snap = video.performance
    if snap is None or metric not in snap.metric_definitions:
        return None
    return (video.source.platform, snap.source, snap.exposure,
            video.publication.content_type, video.publication.declared_format,
            snap.attribution_context, snap.metric_definitions[metric].model_dump_json())


def age_days(video: BenchmarkVideo) -> float | None:
    snap = video.performance
    published = video.publication.published_at
    if snap is None or published is None or snap.observation_window_start != published:
        return None
    if snap.observation_window_end != snap.fetched_at or snap.fetched_at < published:
        return None
    return (snap.fetched_at - published).total_seconds() / 86400


def evaluate(videos: list[BenchmarkVideo], target: BenchmarkVideo, metric: str) -> list[dict]:
    """Return method-specific evidence. The target never enters its own cohort."""
    snap = target.performance
    value = snap.metrics.get(metric) if snap else None
    ctx = context(target, metric)
    source = {"platform": target.source.platform, "snapshot_source": snap.source if snap else None,
              "exposure": snap.exposure if snap else None,
              "account_identifier": target.creator.account_identifier,
              "content_type": target.publication.content_type,
              "declared_format": target.publication.declared_format,
              "attribution_context": snap.attribution_context if snap else None,
              "metric_definition": snap.metric_definitions[metric].model_dump()
              if snap and metric in snap.metric_definitions else None}
    base = {"metric": metric, "source_context": source, "target": target.source.reference,
            "inputs": {"target_value": value}, "limitations": []}

    def result(method, eligible=False, normalized_result=None, reason=None, cohort=None, inputs=None,
               limitations=None):
        return {**base, "method": method, "normalized_result": normalized_result,
                "eligible": eligible, "reason": reason, "sample_size": len(cohort or []),
                "cohort": [item.source.reference for item in cohort or []],
                "inputs": {**base["inputs"], **(inputs or {})},
                "limitations": limitations or []}

    if ctx is None or value is None:
        reason = "metric missing or null; unknown" if snap else "performance snapshot absent"
        return [result(method, reason=reason) for method in METHODS]
    if snap.exposure in ("unknown", "mixed"):
        return [result(method, reason="exposure is unknown or mixed") for method in METHODS]
    if target.creator.account_identifier is None:
        return [result(method, reason="account identity unavailable") for method in METHODS]

    unique = {}
    for video in videos:
        key = source_key(video)
        if key != source_key(target):
            # A repeated source contributes at most once; prefer the latest snapshot.
            previous = unique.get(key)
            if previous is None or (video.performance and previous.performance and
                                    video.performance.fetched_at > previous.performance.fetched_at):
                unique[key] = video
    cohort = [video for video in unique.values()
              if video.creator.account_identifier == target.creator.account_identifier
              and context(video, metric) == ctx and video.performance is not None
              and video.performance.metrics.get(metric) is not None]
    limitations = ["Observational snapshot counts; no causal or quality inference.",
                   "Account and provider context match does not prove identical distribution."]
    if len(cohort) < MIN_COHORT:
        return [result(method, reason=f"insufficient comparable cohort (<{MIN_COHORT})",
                       cohort=cohort, limitations=limitations) for method in METHODS]

    values = [video.performance.metrics[metric] for video in cohort]
    baseline = median(values)
    common = {"cohort": cohort, "inputs": {"cohort_values": values, "account_median": baseline},
              "limitations": limitations}
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
                         cohort=cohort, limitations=limitations) if mad > 0 else
                  result("robust_deviation", reason="zero median absolute deviation", **common))
    target_age = age_days(target)
    aged = [video for video in cohort if age_days(video) is not None and target_age is not None
            and abs(age_days(video) - target_age) <= 2]
    if len(aged) < MIN_COHORT:
        output.append(result("age_matched_percentile", reason="insufficient age-matched cohort or explicit publication windows",
                             cohort=aged, inputs={"target_age_days": target_age}, limitations=limitations))
    else:
        aged_values = [video.performance.metrics[metric] for video in aged]
        aged_rank = 100 * (sum(x < value for x in aged_values) +
                          .5 * sum(x == value for x in aged_values)) / len(aged_values)
        output.append(result("age_matched_percentile", True, aged_rank, cohort=aged,
                             inputs={"target_age_days": target_age, "cohort_values": aged_values,
                                     "tolerance_days": 2}, limitations=limitations +
                             ["Two-day age tolerance is an experiment, not a validated policy."]))
    return output
