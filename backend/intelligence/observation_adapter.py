"""Exact historical observation -> offline Stage 6.1 input. No product calls."""

from intelligence.performance_comparison import PAID_SCOPE


def to_stage61_record(observation: dict) -> dict:
    if observation.get("source") != "meta_ads" or observation.get("placement_scope") != PAID_SCOPE:
        raise ValueError("Unsupported historical observation context.")
    details = dict(observation["metric_payload"])
    if (details.get("date_start") != observation["report_start"].isoformat()
            or details.get("date_stop") != observation["report_end"].isoformat()
            or details.get("account_currency") != observation["account_currency"]
            or details.get("action_report_time") != observation["action_report_time"]
            or details.get("action_attribution_windows") != observation["attribution_windows"]):
        raise ValueError("Historical observation provenance mismatch.")
    return {"reference": str(observation["id"]),
            "provider_id": observation["provider_object_id"], "public_url": None,
            "workspace_id": str(observation["company_id"]),
            "platform": observation["placement_scope"],
            "performance_source": observation["source"],
            "exposure_type": observation["exposure_type"],
            "account_id": observation["provider_account_id"],
            "fetched_at": observation["fetched_at"].isoformat(),
            "performance_metrics": {"meta_ads": details}}
