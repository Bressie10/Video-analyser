"""Read-only, in-memory Stage 6.2 owned Meta Ads cohort experiment.

The caller supplies an existing authorized MetaClient and a workspace identity.
No provider rows, IDs, or comparison reports are written or logged here.
"""

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import re

from app import meta, meta_ads, meta_discovery
from app.ad_metrics import ACTION_FIELDS, ATTRIBUTION_WINDOWS
from intelligence.performance_comparison import MIN_COHORT, PAID_SCOPE, compare

BASE_METRICS = ("impressions", "reach", "clicks", "spend", "ctr", "cpc",
                "cpm", "frequency", "derived_click_rate")


def _pages(client, path, fields, convert):
    cursor, seen = None, set()
    while True:
        page = meta_discovery.listing(client, path, fields, cursor, convert)
        for item in page["items"]:
            yield item
        cursor = page["next_cursor"]
        if cursor is None:
            break
        if cursor in seen:
            raise meta.MetaError("Repeated discovery cursor.")
        seen.add(cursor)


def _owned_accounts(client):
    return list(_pages(client, "me/adaccounts", "id,name",
                       lambda row: meta_discovery.item(row, "ad_account", "Advertising account")))


def _ad_items(client, account_id):
    return list(_pages(client, f"{account_id}/ads",
                       "id,name,effective_status,created_time,creative{thumbnail_url}",
                       lambda row: meta_discovery.item(row, "Ad", "Untitled ad")))


def _record(ad_id, account_id, workspace_id, details, fetched_at):
    return {"reference": ad_id, "provider_id": ad_id, "public_url": None,
            "workspace_id": workspace_id, "platform": PAID_SCOPE,
            "performance_source": "meta_ads", "exposure_type": "paid",
            "account_id": account_id, "fetched_at": fetched_at,
            "performance_metrics": {"meta_ads": details}}


def _context_reason(details):
    if not details.get("account_currency"):
        return "missing_currency"
    if details.get("action_report_time") != "impression" or details.get("action_attribution_windows") != list(ATTRIBUTION_WINDOWS):
        return "attribution_configuration_mismatch"
    return None


def collect(client, workspace_id: str, account_id: str, since: date, until: date):
    """Return private records plus an aggregate audit; never serialize the records to Git."""
    if not isinstance(workspace_id, str) or not workspace_id or not re.fullmatch(r"act_[0-9]{1,30}", account_id):
        raise ValueError("Explicit workspace and numeric act_ account are required.")
    if not isinstance(since, date) or not isinstance(until, date) or since > until:
        raise ValueError("Explicit ordered report dates are required.")
    if account_id not in {row["id"] for row in _owned_accounts(client)}:
        raise meta.MetaPermissionError("Selected ad account is not owned by this session.")
    items = _ad_items(client, account_id)
    reasons = Counter()
    seen, records = set(), []
    for item in sorted(items, key=lambda row: row["id"]):
        ad_id = item["id"]
        if ad_id in seen:
            reasons["duplicate_ad_identity"] += 1
            continue
        seen.add(ad_id)
        try:
            identity = client.get(ad_id, {"fields": "id,account_id"})
            if identity.get("id") != ad_id or identity.get("account_id") != account_id.removeprefix("act_"):
                reasons["account_mismatch"] += 1
                continue
            snapshot = meta_ads.ad_performance(client, ad_id, since, until)
            details = snapshot["performance_metrics"]["meta_ads"]
            reason = _context_reason(details)
            if reason:
                reasons[reason] += 1
                continue
            records.append(_record(ad_id, account_id, workspace_id, details,
                                   datetime.now(timezone.utc).isoformat()))
        except meta_ads.AdMetricsUnavailable:
            reasons["no_usable_insights"] += 1
        except (meta.MetaNotConnected, meta.MetaPermissionError, meta.MetaConfigurationError):
            raise
        except meta.MetaError:
            reasons["malformed_or_unavailable_insights"] += 1
    audit = {"discovered": len(items), "distinct_discovered": len(seen),
             "usable_insights": len(records), "eligible": len(records),
             "excluded": len(items) - len(records),
             "exclusion_reasons": dict(sorted(reasons.items())),
             "cohort_status": "eligible" if len(records) >= MIN_COHORT + 1 else "insufficient_real_cohort"}
    return records, audit


def experiment(records):
    """Return aggregate findings only; raw Stage 6.1 reports stay in memory."""
    if len({row["provider_id"] for row in records}) < MIN_COHORT + 1:
        return {"status": "insufficient_real_cohort", "metrics_comparable": [],
                "ctr_vs_derived_click_rate": "not_evaluated", "action_type_diversity": {}}
    ordered = sorted(records, key=lambda row: row["provider_id"])
    targets = ordered[:3]
    action_types = Counter()
    action_metrics = set()
    for row in ordered:
        details = row["performance_metrics"]["meta_ads"]
        for collection in ACTION_FIELDS:
            for action in details.get(collection) or []:
                action_types[(collection, action["action_type"])] += 1
                for window in ATTRIBUTION_WINDOWS:
                    if action.get(window) is not None:
                        action_metrics.add(f"action:{collection}:{action['action_type']}:{window}")
    metrics = [*BASE_METRICS, *sorted(action_metrics)]
    comparable = set()
    for target in targets:
        result = compare(target, ordered, metrics)
        comparable.update(row["metric_id"] for row in result["metric_comparisons"] if row["eligibility"])
    differences, observations = 0, 0
    for row in ordered:
        details = row["performance_metrics"]["meta_ads"]
        if details.get("ctr") is not None and details.get("clicks") is not None and details.get("impressions"):
            observations += 1
            differences += Decimal(details["ctr"]) != Decimal(details["clicks"]) / Decimal(details["impressions"]) * 100
    return {"status": "evaluated", "targets_evaluated": len(targets),
            "metrics_comparable": sorted(comparable),
            "ctr_vs_derived_click_rate": {"pairs": observations, "different": differences},
            "action_type_diversity": {"distinct_collection_types": len(action_types),
                                      "collections": dict(sorted(Counter(key[0] for key in action_types).items()))},
            "provider_cpc_denominator": "unproven_against_generic_clicks"}


def run_with_session(session_id: str, workspace_id: str, account_id: str,
                     since: date, until: date):
    """Run inside the process holding the authorized session; return aggregates only."""
    records, audit = collect(meta.session_client(session_id), workspace_id,
                             account_id, since, until)
    return {**audit, **experiment(records)}
