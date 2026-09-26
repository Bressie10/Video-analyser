"""Instagram Reel insights mapped to the common performance snapshot."""

import re

from app.meta import MetaClient, MetaError
from app.performance import VideoPerformance, performance_snapshot

INSIGHT_FIELDS = {
    "views": "view_count",
    "likes": "like_count",
    "comments": "comment_count",
    "shares": "share_count",
}


class NotInstagramReel(ValueError):
    pass


class InstagramMetricsUnavailable(ValueError):
    pass


def _metric_value(row: dict) -> int | None:
    if row.get("period") != "lifetime":
        raise MetaError("Instagram returned an unexpected metric period.")
    # Media insights without breakdowns contain a single lifetime value.
    values = row.get("values")
    if values is None or values == []:
        return None
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise MetaError("Instagram returned invalid metric values.")
    return values[0].get("value")


def reel_performance(client: MetaClient, media_id: str, *, allow_video: bool = False) -> VideoPerformance:
    """Read only this Reel's organic Instagram metrics using the existing token."""
    if not re.fullmatch(r"[0-9]{1,30}", media_id):
        raise NotInstagramReel("Provide the numeric Instagram Graph media ID.")
    media = client.get(media_id, {"fields": "id,media_type,media_product_type"})
    if media.get("id") != media_id:
        raise MetaError("Instagram returned a different media ID.")
    if (not allow_video and media.get("media_product_type") != "REELS") or media.get("media_type") != "VIDEO":
        raise NotInstagramReel("The Instagram media must be a Reel.")

    payload = client.get(f"{media_id}/insights", {"metric": ",".join(INSIGHT_FIELDS)})
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise MetaError("Instagram returned an invalid insights response.")
    counts = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise MetaError("Instagram returned an invalid insight.")
        name = row["name"]
        if name not in INSIGHT_FIELDS:
            continue
        if name in seen:
            raise MetaError("Instagram returned duplicate insights.")
        seen.add(name)
        if "id" in row and row["id"] != f"{media_id}/insights/{name}/lifetime":
            raise MetaError("Instagram returned insights for a different media or period.")
        counts[INSIGHT_FIELDS[name]] = _metric_value(row)
    if not any(value is not None for value in counts.values()):
        raise InstagramMetricsUnavailable("Instagram has no available performance counts for this Reel.")
    try:
        return performance_snapshot("instagram", counts)
    except ValueError:
        raise MetaError("Instagram returned invalid performance counts.") from None
