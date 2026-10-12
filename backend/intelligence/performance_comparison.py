"""Stage 6.1 offline, observational performance comparisons. No product imports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from statistics import median

SCHEMA_VERSION = "v9-stage6.1-1"
MIN_COHORT = 5
AGE_TOLERANCE_DAYS = 2  # Research hypothesis, not a provider rule.
ORGANIC = ("instagram", "facebook", "tiktok")
PAID = "meta_ads"
PAID_SCOPE = "meta_all_placements"
COUNTS = ("view_count", "like_count", "comment_count", "share_count")
AD_COUNTS = ("impressions", "reach", "clicks")
AD_RATES = ("ctr", "cpc")
ACTION_COLLECTIONS = ("actions", "conversions", "video_play_actions")
WINDOWS = ("7d_click", "1d_view")


def metric_definition(metric_id: str, source: str) -> dict:
    """An exact research definition; provider rates remain provider rates."""
    common = {"metric_id": metric_id, "source": source,
              "exposure_type": "paid" if source == PAID else "organic"}
    if source in ORGANIC and metric_id in COUNTS:
        return {**common, "description": f"Provider {metric_id} snapshot",
                "unit": "count", "raw_or_derived": "raw", "formula": None,
                "required_inputs": [metric_id],
                "comparison_direction": "higher_means_more_observed_count",
                "limitations": ["Publication age and exposure affect counts; provider definitions are distinct."]}
    paid = {
        "impressions": ("delivered impressions", "count", "raw", None, ["impressions"], "higher_means_more_delivery"),
        "reach": ("reported reach", "count", "raw", None, ["reach"], "higher_means_more_reported_reach"),
        "clicks": ("reported clicks", "count", "raw", None, ["clicks"], "higher_means_more_reported_clicks"),
        "spend": ("reported spend", "account currency", "raw", None, ["spend", "account_currency"], "higher_means_more_spend"),
        "ctr": ("provider-reported CTR", "percent", "raw", None, ["ctr"], "higher_means_higher_reported_click_rate"),
        "cpc": ("provider-reported CPC", "account currency/click", "raw", None, ["cpc", "account_currency"], "lower_means_lower_reported_cost_per_click"),
        "cpm": ("derived cost per thousand impressions", "account currency/1000 impressions", "derived", "spend / impressions * 1000", ["spend", "impressions", "account_currency"], "lower_means_lower_cost_per_thousand_impressions"),
        "frequency": ("derived impressions per reached account", "impressions/reached account", "derived", "impressions / reach", ["impressions", "reach"], "higher_means_more_impressions_per_reached_account"),
        "derived_click_rate": ("derived clicks per impression", "percent", "derived", "clicks / impressions * 100", ["clicks", "impressions"], "higher_means_higher_derived_click_rate"),
    }
    if source == PAID and metric_id in paid:
        description, unit, kind, formula, inputs, direction = paid[metric_id]
        return {**common, "description": description, "unit": unit,
                "raw_or_derived": kind, "formula": formula, "required_inputs": inputs,
                "comparison_direction": direction,
                "limitations": ["Equal reporting windows do not establish equal delivery opportunity."]}
    parts = metric_id.split(":")
    if source == PAID and len(parts) >= 4 and parts[0] in ("action", "cost_per_action") and parts[1] in ACTION_COLLECTIONS and parts[-1] in WINDOWS and all(parts[2:-1]):
        kind, collection, action_type, window = parts[0], parts[1], ":".join(parts[2:-1]), parts[-1]
        raw = kind == "action"
        return {**common, "description": f"{collection} {action_type} at {window}" if raw else
                f"cost per {collection} {action_type} at {window}",
                "unit": "attributed actions" if raw else "account currency/attributed action",
                "raw_or_derived": "raw" if raw else "derived",
                "formula": None if raw else "spend / attributed_action_count",
                "required_inputs": [f"{collection}:{action_type}:{window}"] if raw else
                ["spend", "account_currency", f"{collection}:{action_type}:{window}"],
                "comparison_direction": "higher_means_more_reported_attributed_actions" if raw else
                "lower_means_lower_cost_per_reported_attributed_action",
                "limitations": ["Attribution windows and action types must remain separate; collections may overlap."]}
    raise ValueError("unsupported_metric")


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _date(value):
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        return result if result is not None and result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _value(record: dict, metric_id: str) -> tuple[Decimal | None, str | None, dict]:
    details = record.get("performance_metrics") or {}
    if record.get("performance_source") == PAID:
        details = details.get("meta_ads") or {}
    definition = metric_definition(metric_id, record.get("performance_source"))
    provenance = {"formula": definition["formula"], "inputs": {}, "source": definition["source"]}
    if metric_id.startswith(("action:", "cost_per_action:")):
        parts = metric_id.split(":")
        collection, action_type, window = parts[1], ":".join(parts[2:-1]), parts[-1]
        rows = details.get(collection)
        matches = [row for row in rows if row.get("action_type") == action_type] if isinstance(rows, list) else []
        if len(matches) != 1:
            return None, "missing_action_type", provenance
        count = _number(matches[0].get(window))
        provenance["inputs"] = {"collection": collection, "action_type": action_type,
                                "attribution_window": window, "count": matches[0].get(window)}
        if count is None:
            return None, "missing_attribution_window_value", provenance
        if metric_id.startswith("action:"):
            return count, None, provenance
        spend = _number(details.get("spend"))
        provenance["inputs"].update({"spend": details.get("spend"),
                                     "account_currency": details.get("account_currency")})
        if not details.get("account_currency"):
            return None, "missing_currency", provenance
        if spend is None:
            return None, "missing_metric", provenance
        return (spend / count, None, provenance) if count > 0 else (None, "zero_denominator", provenance)
    if metric_id in ("cpm", "frequency", "derived_click_rate"):
        numerator, denominator, factor = {
            "cpm": ("spend", "impressions", 1000),
            "frequency": ("impressions", "reach", 1),
            "derived_click_rate": ("clicks", "impressions", 100),
        }[metric_id]
        provenance["inputs"] = {key: details.get(key) for key in (numerator, denominator)}
        if metric_id == "cpm":
            provenance["inputs"]["account_currency"] = details.get("account_currency")
            if not details.get("account_currency"):
                return None, "missing_currency", provenance
        top, bottom = _number(details.get(numerator)), _number(details.get(denominator))
        if top is None or bottom is None:
            return None, "missing_metric", provenance
        return (top / bottom * factor, None, provenance) if bottom > 0 else (None, "zero_denominator", provenance)
    value = details.get(metric_id)
    provenance["inputs"] = {metric_id: value}
    if metric_id in ("spend", "cpc") and not details.get("account_currency"):
        return None, "missing_currency", provenance
    parsed = _number(value)
    return parsed, None if parsed is not None else "missing_metric", provenance


def _context(record: dict, metric_id: str) -> dict:
    paid = record.get("performance_source") == PAID
    ads = (record.get("performance_metrics") or {}).get("meta_ads") or {} if paid else {}
    context = {"workspace_id": record.get("workspace_id"), "platform": record.get("platform"),
               "performance_source": record.get("performance_source"),
               "exposure_type": record.get("exposure_type"), "account_id": record.get("account_id"),
               "metric_id": metric_id, "metric_definition": metric_definition(metric_id, record.get("performance_source")),
               "provider_metric_definition": (record.get("metric_definitions") or {}).get(metric_id)}
    if paid:
        context.update({"date_start": ads.get("date_start"), "date_stop": ads.get("date_stop"),
                        "action_report_time": ads.get("action_report_time"),
                        "action_attribution_windows": ads.get("action_attribution_windows")})
        if metric_id in ("spend", "cpc", "cpm") or metric_id.startswith("cost_per_action:"):
            context["account_currency"] = ads.get("account_currency")
    else:
        context.update({"content_type": record.get("content_type"),
                        "declared_format": record.get("declared_format"),
                        "age_tolerance_days": AGE_TOLERANCE_DAYS})
    return context


def _context_errors(record: dict, metric_id: str) -> list[str]:
    context = _context(record, metric_id)
    required = ("workspace_id", "platform", "performance_source", "exposure_type", "account_id")
    errors = [f"missing_{key}" for key in required if not context.get(key)]
    paid = record.get("performance_source") == PAID
    if not paid and record.get("performance_source") != record.get("platform"):
        errors.append("source_platform_mismatch")
    if paid and record.get("platform") != PAID_SCOPE:
        errors.append("unsupported_paid_platform")
    if paid:
        errors += [f"missing_{key}" for key in ("date_start", "date_stop", "action_report_time",
                   "action_attribution_windows") if not context.get(key)]
        try:
            if date.fromisoformat(context["date_start"]) > date.fromisoformat(context["date_stop"]):
                errors.append("invalid_reporting_range")
        except (TypeError, ValueError):
            errors.append("invalid_reporting_range")
        if not isinstance(context.get("action_attribution_windows"), list):
            errors.append("invalid_attribution_configuration")
        if "account_currency" in context and not context["account_currency"]:
            errors.append("missing_currency")
    else:
        errors += [f"missing_{key}" for key in ("content_type", "declared_format") if not context.get(key)]
        if _age(record) is None:
            errors.append("missing_publication_or_observation_time")
    return errors


def _age(record):
    published, observed = _date(record.get("published_at")), _date(record.get("observed_at"))
    if not published or not observed or observed < published:
        return None
    return (observed - published).total_seconds() / 86400


def _tokens(record):
    return {(record.get("platform"), kind, value) for kind, value in
            (("provider_id", record.get("provider_id")), ("public_url", record.get("public_url"))) if value}


def _identity(record):
    return {key: record.get(key) for key in ("reference", "provider_id", "public_url",
                                             "workspace_id", "platform", "account_id")}


def _fingerprint(context):
    return sha256(json.dumps(context, sort_keys=True, separators=(",", ":"),
                             default=str).encode()).hexdigest()


def compare(target: dict, candidates: list[dict], metric_ids: list[str]) -> dict:
    """Compare each registered metric independently; input records are never changed."""
    source = target.get("performance_source")
    family = "paid" if source == PAID else "organic" if source in ORGANIC else None
    if family is None:
        raise ValueError("unsupported_source")
    if target.get("exposure_type") != family:
        raise ValueError("target_exposure_mismatch")
    if not _tokens(target):
        raise ValueError("target_identity_missing")
    for metric in metric_ids:
        metric_definition(metric, source)
    ordered_metrics = sorted(set(metric_ids))
    report = {"schema_version": SCHEMA_VERSION, "comparison_family": family,
              "target_identity": _identity(target),
              "target_performance_provenance": {key: target.get(key) for key in
                                               ("performance_source", "exposure_type", "observed_at", "fetched_at")},
              "cohort_definition": {"minimum_peers": MIN_COHORT,
                                    "age_tolerance_days": AGE_TOLERANCE_DAYS if family == "organic" else None,
                                    "target_excluded": True},
              "cohort_member_identities": {}, "excluded_candidate_peers": {},
              "deduplicated_records": {}, "target_exclusion_proof": {},
              "metric_comparisons": [],
              "limitations": ["Observational comparison only; no causal inference or semantic technique is involved.",
                              "Provider equivalence is not assumed; no overall performance score exists."]}
    # Identity closure prevents a provider-ID alias from returning through a URL-only row.
    target_tokens = _tokens(target)
    while True:
        expanded = target_tokens | set().union(*(_tokens(row) for row in candidates
                                                  if _tokens(row) & target_tokens)) if candidates else target_tokens
        if expanded == target_tokens:
            break
        target_tokens = expanded
    for metric in ordered_metrics:
        definition = metric_definition(metric, source)
        context = _context(target, metric)
        fingerprint = _fingerprint(context)
        target_value, target_value_reason, target_inputs = _value(target, metric)
        target_errors = _context_errors(target, metric)
        if target_value_reason:
            target_errors.append(target_value_reason)
        eligible, excluded, aliases = [], [], []
        for row in candidates:
            reasons = []
            if _tokens(row) & target_tokens:
                reasons.append("target_identity_alias")
                aliases.append(_identity(row))
            else:
                if row.get("performance_source") != source:
                    reasons.append("performance_source_mismatch")
                if row.get("exposure_type") != family:
                    reasons.append("exposure_type_mismatch")
                if row.get("platform") != target.get("platform"):
                    reasons.append("platform_mismatch")
                if row.get("workspace_id") != target.get("workspace_id"):
                    reasons.append("workspace_mismatch")
                if row.get("account_id") != target.get("account_id"):
                    reasons.append("account_mismatch")
                if not reasons:
                    peer_context = _context(row, metric)
                    for key in context:
                        if key not in ("workspace_id", "platform", "performance_source", "exposure_type", "account_id") and peer_context[key] != context[key]:
                            reasons.append(f"{key}_mismatch")
                    reasons.extend(_context_errors(row, metric))
                    if family == "organic" and _age(row) is not None and _age(target) is not None and abs(_age(row) - _age(target)) > AGE_TOLERANCE_DAYS:
                        reasons.append("publication_age_mismatch")
                    value, value_reason, inputs = _value(row, metric)
                    if value_reason:
                        reasons.append(value_reason)
                    if not reasons:
                        eligible.append((row, value, inputs))
            if reasons:
                excluded.append({"identity": _identity(row), "reasons": sorted(set(reasons))})
        # Collapse connected components of exact provider ID / URL aliases after eligibility.
        groups = []
        for item in eligible:
            tokens = _tokens(item[0])
            matching = [group for group in groups if group[0] & tokens]
            for group in matching:
                groups.remove(group)
                tokens |= group[0]
            groups.append((tokens, [item, *(member for group in matching for member in group[1])]))
        cohort, dedup = [], []
        for _, members in groups:
            members.sort(key=lambda item: (str(item[0].get("fetched_at") or ""),
                                           json.dumps(item[0], sort_keys=True, default=str)), reverse=True)
            cohort.append(members[0])
            dedup.extend({"identity": _identity(item[0]), "retained": _identity(members[0][0]),
                          "reason": "exact_provider_identity_alias"} for item in members[1:])
        cohort.sort(key=lambda item: json.dumps(_identity(item[0]), sort_keys=True))
        excluded.sort(key=lambda item: json.dumps(item["identity"], sort_keys=True))
        dedup.sort(key=lambda item: json.dumps(item["identity"], sort_keys=True))
        report["cohort_member_identities"][metric] = [_identity(item[0]) for item in cohort]
        report["excluded_candidate_peers"][metric] = excluded
        report["deduplicated_records"][metric] = dedup
        report["target_exclusion_proof"][metric] = {"target_tokens": sorted(target_tokens),
                                                     "excluded_aliases": sorted(aliases, key=lambda x: json.dumps(x, sort_keys=True)),
                                                     "cohort_has_target_alias": any(_tokens(item[0]) & target_tokens for item in cohort)}
        reasons = sorted(set(target_errors))
        if len(cohort) < MIN_COHORT:
            reasons.append("insufficient_peer_cohort")
        values = [item[1] for item in cohort]
        result = {"metric_id": metric, "metric_definition": definition,
                  "raw_or_derived_provenance": definition["raw_or_derived"],
                  "context_fingerprint": fingerprint, "comparison_context": context,
                  "target_value": str(target_value) if target_value is not None else None,
                  "peer_values": [{"identity": _identity(row), "value": str(value), "formula_input_provenance": inputs}
                                  for row, value, inputs in cohort],
                  "sample_size": len(cohort), "median": None, "delta": None,
                  "ratio": None, "log_ratio": None, "percentile": None,
                  "mad": None, "robust_deviation": None,
                  "age_matched_percentile": None, "eligibility": not reasons,
                  "abstention_reasons": reasons, "method_abstentions": [],
                  "formula_input_provenance": target_inputs}
        if not reasons:
            baseline = median(values)
            delta = target_value - baseline
            mad = median(abs(value - baseline) for value in values)
            result.update({"median": str(baseline), "delta": str(delta), "mad": str(mad),
                           "percentile": 100 * (sum(value < target_value for value in values) +
                                                .5 * sum(value == target_value for value in values)) / len(values)})
            if baseline > 0:
                ratio = target_value / baseline
                result["ratio"] = str(ratio)
                if ratio > 0:
                    result["log_ratio"] = math.log(float(ratio))
                else:
                    result["method_abstentions"].append("log_ratio_zero_target")
            else:
                result["method_abstentions"].extend(("ratio_zero_median", "log_ratio_zero_median"))
            if mad > 0:
                result["robust_deviation"] = str(delta / (Decimal("1.4826") * mad))
            else:
                result["method_abstentions"].append("robust_deviation_zero_mad")
            if family == "organic":
                result["age_matched_percentile"] = result["percentile"]
        report["metric_comparisons"].append(result)
    return report
