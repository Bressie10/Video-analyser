"""Offline, deterministic interpretation of validated Stage 6 comparisons."""

from decimal import Decimal, InvalidOperation
import re

from intelligence.performance_comparison import (
    MIN_COHORT, ORGANIC, PAID, SCHEMA_VERSION as COMPARISON_VERSION, metric_definition,
)

SCHEMA_VERSION = "v9-stage7.1-1"
# Research presentation thresholds, not significance tests or success scores.
HIGH_PERCENTILE, LOW_PERCENTILE = 80, 20
HIGH_RATIO, LOW_RATIO = Decimal("1.25"), Decimal("0.80")
ROBUST_DEVIATION = Decimal("1")
PRESENTATION_ORDER = ("ctr", "derived_click_rate", "cpc", "cpm", "impressions",
                      "reach", "clicks", "spend", "frequency")
FORBIDDEN_CAUSAL = re.compile(
    r"\b(?:caus(?:e|es|ed)|dr(?:ove|ives)|resulted in|led to|because|"
    r"due to the creative|this technique improved|this hook increased|proves?)\b",
    re.IGNORECASE,
)


def _decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid Stage 6 numeric evidence.") from None
    if not number.is_finite():
        raise ValueError("Invalid Stage 6 numeric evidence.")
    return number


def _optional_decimal(value):
    return None if value is None else _decimal(value)


def evidence_summary(report: dict) -> dict:
    """Keep only Stage 6 facts relevant to performance interpretation."""
    if report.get("schema_version") != COMPARISON_VERSION or report.get("comparison_family") not in ("paid", "organic"):
        raise ValueError("Unsupported Stage 6 comparison report.")
    summary = {"schema_version": SCHEMA_VERSION,
               "comparison_family": report["comparison_family"],
               "metrics": [], "unavailable_metrics": [], "limitations": list(report.get("limitations") or [])}
    for row in report["metric_comparisons"]:
        metric_id = row["metric_id"]
        if not row["eligibility"]:
            summary["unavailable_metrics"].append({"metric_id": metric_id,
                "abstention_reasons": list(row["abstention_reasons"])})
            continue
        definition = row["metric_definition"]
        source = definition.get("source")
        valid_source = source == PAID if report["comparison_family"] == "paid" else source in ORGANIC
        if not valid_source:
            raise ValueError("Stage 6 metric family mismatch.")
        if (definition != metric_definition(metric_id, source)
                or row["raw_or_derived_provenance"] != definition["raw_or_derived"]):
            raise ValueError("Stage 6 metric definition mismatch.")
        target, median = _decimal(row["target_value"]), _decimal(row["median"])
        ratio = _optional_decimal(row.get("ratio"))
        percentile = _decimal(row["percentile"])
        robust = _optional_decimal(row.get("robust_deviation"))
        size = row["sample_size"]
        if (not isinstance(size, int) or isinstance(size, bool) or size < MIN_COHORT
                or not 0 <= percentile <= 100 or ratio is not None and ratio < 0
                or not re.fullmatch(r"[0-9a-f]{64}", row["context_fingerprint"])):
            raise ValueError("Invalid eligible Stage 6 metric.")
        summary["metrics"].append({
            "metric_id": metric_id, "description": definition["description"],
            "direction_semantics": definition["comparison_direction"],
            "raw_or_derived": row["raw_or_derived_provenance"],
            "target_value": str(target), "median": str(median),
            "ratio": str(ratio) if ratio is not None else None,
            "percentile": float(percentile),
            "robust_deviation": str(robust) if robust is not None else None,
            "sample_size": size, "context_fingerprint": row["context_fingerprint"],
            "limitations": list(definition.get("limitations") or []),
            "method_abstentions": list(row.get("method_abstentions") or []),
            "excluded_count": len(report.get("excluded_candidate_peers", {}).get(metric_id, [])),
        })
    summary["metrics"].sort(key=lambda item: item["metric_id"])
    summary["unavailable_metrics"].sort(key=lambda item: item["metric_id"])
    return summary


def _direction(metric):
    target, median = _decimal(metric["target_value"]), _decimal(metric["median"])
    return "above_cohort" if target > median else "below_cohort" if target < median else "near_cohort"


def _notable(metric):
    percentile = metric["percentile"]
    ratio = _optional_decimal(metric["ratio"])
    robust = _optional_decimal(metric["robust_deviation"])
    return (percentile >= HIGH_PERCENTILE or percentile <= LOW_PERCENTILE
            or ratio is not None and (ratio >= HIGH_RATIO or ratio <= LOW_RATIO)
            or robust is not None and abs(robust) >= ROBUST_DEVIATION)


def _label(metric):
    return metric["metric_id"].upper() if metric["metric_id"] in ("ctr", "cpc", "cpm") else metric["description"]


def guard_language(value: str) -> str:
    """Fail closed if a future template introduces unsupported causal language."""
    if FORBIDDEN_CAUSAL.search(value):
        raise ValueError("Unsupported causal language in performance reasoning.")
    return value


def reason(report: dict) -> dict:
    evidence = evidence_summary(report)
    notable, near = [], []
    for metric in evidence["metrics"]:
        direction = _direction(metric)
        if _notable(metric) and direction != "near_cohort":
            notable.append({"metric_id": metric["metric_id"], "direction": direction,
                "observation": guard_language(
                    f"{metric['description'].capitalize()} was {'above' if direction == 'above_cohort' else 'below'} "
                    "this comparison cohort's median."),
                "target_value": metric["target_value"], "median": metric["median"],
                "ratio_to_median": metric["ratio"], "percentile": metric["percentile"],
                "robust_deviation": metric["robust_deviation"],
                "sample_size": metric["sample_size"],
                "context_fingerprint": metric["context_fingerprint"],
                "direction_semantics": metric["direction_semantics"],
                "raw_or_derived": metric["raw_or_derived"]})
        else:
            near.append(metric["metric_id"])
    notable.sort(key=lambda item: (PRESENTATION_ORDER.index(item["metric_id"])
                                   if item["metric_id"] in PRESENTATION_ORDER else len(PRESENTATION_ORDER),
                                   item["metric_id"]))
    by_id = {item["metric_id"]: item["direction"] for item in notable}
    conflicts = []
    pairs = (
        ("ctr", "above_cohort", "cpc", "above_cohort",
         "Higher observed click rate accompanied higher cost per click."),
        ("impressions", "above_cohort", "ctr", "below_cohort",
         "More delivered impressions accompanied a lower observed click rate."),
        ("ctr", "above_cohort", "derived_click_rate", "below_cohort",
         "Provider CTR and derived click rate point in different directions."),
        ("ctr", "below_cohort", "derived_click_rate", "above_cohort",
         "Provider CTR and derived click rate point in different directions."),
    )
    for left, left_direction, right, right_direction, message in pairs:
        if by_id.get(left) == left_direction and by_id.get(right) == right_direction:
            conflicts.append({"metric_ids": [left, right], "observation": message})
    for action in (item for item in notable if item["metric_id"].startswith("action:")):
        cost_id = "cost_per_action:" + action["metric_id"].split(":", 1)[1]
        if action["direction"] == "above_cohort" and by_id.get(cost_id) == "above_cohort":
            conflicts.append({"metric_ids": [action["metric_id"], cost_id],
                              "observation": "More attributed actions accompanied higher cost per attributed action."})
    size = min((metric["sample_size"] for metric in evidence["metrics"]), default=None)
    unit = "peer ads" if evidence["comparison_family"] == "paid" else "peer posts"
    prefix = f"Among {size} comparable {unit}, " if size is not None else "For this comparison, "
    if notable:
        labels = {metric["metric_id"]: _label(metric) for metric in evidence["metrics"]}
        clauses = [f"{labels[item['metric_id']]} was "
                   f"{'above' if item['direction'] == 'above_cohort' else 'below'} the cohort median"
                   for item in notable[:3]]
        summary_text = prefix + "; ".join(clauses) + "."
    elif evidence["metrics"]:
        summary_text = prefix + "eligible metrics were near their cohort medians."
    else:
        summary_text = "No eligible metrics were available for performance reasoning."
    if conflicts:
        summary_text += " " + conflicts[0]["observation"]
    elif near and notable:
        near_labels = [_label(metric) for metric in evidence["metrics"] if metric["metric_id"] in near][:2]
        summary_text += " " + " and ".join(near_labels) + " remained near the cohort baseline."
    limitations = ["Observational cohort comparison; no causal conclusion or account-wide generalization."]
    if size is not None and size <= MIN_COHORT:
        limitations.append("Small peer cohort; percentile values have limited resolution.")
    limitations.extend(evidence["limitations"])
    result = {"schema_version": SCHEMA_VERSION, "summary": guard_language(summary_text),
              "notable_metrics": notable, "mixed_signals": conflicts,
              "abstentions": evidence["unavailable_metrics"],
              "limitations": limitations,
              "evidence_refs": [{"metric_id": metric["metric_id"],
                                 "context_fingerprint": metric["context_fingerprint"],
                                 "sample_size": metric["sample_size"]}
                                for metric in evidence["metrics"]]}
    for conflict in conflicts:
        guard_language(conflict["observation"])
    return result
