"""Common performance snapshot contract, independent of provider response formats."""

from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict, get_args

from app.ad_metrics import has_ad_values, normalize_ad_metrics

PerformanceSource = Literal["tiktok", "instagram", "facebook", "meta_ads"]
METRIC_FIELDS = ("view_count", "like_count", "comment_count", "share_count")


class PerformanceMetrics(TypedDict):
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None
    meta_ads: NotRequired[dict]


class VideoPerformance(TypedDict):
    performance_source: PerformanceSource
    performance_metrics: PerformanceMetrics


def performance_snapshot(source: PerformanceSource, values: Mapping[str, object]) -> VideoPerformance:
    """Keep provenance separate from counts; missing values remain unknown."""
    if source not in get_args(PerformanceSource):
        raise ValueError("Unsupported performance source.")
    counts = {field: values.get(field) for field in METRIC_FIELDS}
    if any(value is not None and (
        type(value) is not int or not 0 <= value <= 9223372036854775807
    ) for value in counts.values()):
        raise ValueError("Performance counts must be non-negative BIGINT integers or null.")
    details = None
    if values.get("meta_ads") is not None:
        if source != "meta_ads":
            raise ValueError("Ad metrics require the meta_ads source.")
        details = normalize_ad_metrics(values["meta_ads"])
    if all(value is None for value in counts.values()) and not (details and has_ad_values(details)):
        raise ValueError("At least one performance count is required.")
    if details is not None:
        counts["meta_ads"] = details
    return {
        "performance_source": source,
        "performance_metrics": PerformanceMetrics(**counts),
    }
