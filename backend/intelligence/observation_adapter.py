"""Exact historical observation -> offline Stage 6.1 input. No product calls."""

from intelligence.performance_comparison import PAID_SCOPE


def latest_observations_for_cohort(observations: list[dict]) -> list[dict]:
    """Choose one latest fetch per provider object from an exact-context read.

    The repository retains and returns every version for provenance. A cohort
    must be built from this selection before metric eligibility is evaluated,
    so an older value cannot replace a newer observation with a missing metric.
    """
    latest = {}
    for row in observations:
        identity = (row["company_id"], row["source"], row["provider_account_id"],
                    row["provider_object_type"], row["provider_object_id"])
        current = latest.get(identity)
        if current is None or (row["fetched_at"], row["id"]) > (current["fetched_at"], current["id"]):
            latest[identity] = row
    return [latest[key] for key in sorted(latest, key=lambda item: tuple(map(str, item)))]


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
