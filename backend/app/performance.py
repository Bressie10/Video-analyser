"""Common performance snapshot contract, independent of provider response formats."""

from collections.abc import Mapping
from typing import Literal, TypedDict, get_args

PerformanceSource = Literal["tiktok", "instagram", "facebook", "meta_ads"]
METRIC_FIELDS = ("view_count", "like_count", "comment_count", "share_count")


class PerformanceMetrics(TypedDict):
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None


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
    if all(value is None for value in counts.values()):
        raise ValueError("At least one performance count is required.")
    return {
        "performance_source": source,
        "performance_metrics": PerformanceMetrics(**counts),
    }
