"""Optional organic exposure metrics, kept separate from legacy count contracts."""

from app import facebook, instagram, meta
from app.performance import METRIC_FIELDS


def organic_performance(client, item):
    """A reach-only response is useful even when engagement counts are absent."""
    try:
        if item["platform"] == "instagram":
            snapshot = instagram.reel_performance(
                client, item["external_id"], allow_video=True
            )
        else:
            snapshot = facebook.video_performance(
                client,
                item["account_external_id"],
                item["external_id"],
                "reels" if item["content_type"] == "reel" else "videos",
            )
    except (instagram.InstagramMetricsUnavailable, facebook.FacebookMetricsUnavailable):
        extra = exposure_metrics(client, item)
        if not extra:
            raise
        return {
            "performance_source": item["platform"],
            "performance_metrics": {**dict.fromkeys(METRIC_FIELDS), **extra},
        }
    return {
        **snapshot,
        "performance_metrics": {
            **snapshot["performance_metrics"],
            **exposure_metrics(client, item),
        },
    }


def exposure_metrics(client, item):
    if item["platform"] == "instagram":
        provider = client
        path = f"{item['external_id']}/insights"
        fields = {"reach": "reach"}
    elif (
        item["platform"] == "facebook"
        and item["content_type"] == "video"
        and item["account_external_id"].isdigit()
    ):
        provider = client.for_page(item["account_external_id"])
        path = f"{item['external_id']}/video_insights"
        fields = {
            "total_video_impressions": "impressions",
            "total_video_impressions_unique": "reach",
        }
    else:
        return {}
    result = {}
    for metric, name in fields.items():
        try:
            payload = provider.get(path, {"metric": metric, "period": "lifetime"})
            rows = payload.get("data")
            if not isinstance(rows, list) or len(rows) != 1:
                continue
            row = rows[0]
            if (
                not isinstance(row, dict)
                or row.get("name") != metric
                or row.get("period") != "lifetime"
            ):
                continue
            if "id" in row and row["id"] != f"{path}/{metric}/lifetime":
                continue
            values = row.get("values")
            value = (
                values[0].get("value")
                if isinstance(values, list)
                and len(values) == 1
                and isinstance(values[0], dict)
                else None
            )
            if type(value) is int and 0 <= value <= 9223372036854775807:
                result[name] = value
        except meta.MetaNotConnected:
            raise
        except meta.MetaError:
            # An unavailable optional field must not discard supported engagement.
            continue
    return result
