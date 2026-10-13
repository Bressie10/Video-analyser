"""One on-demand, company-authorized path through the frozen V9 stages."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi import HTTPException

from app import meta, meta_library_repository as library
from app.company_authorization import authorize
from app.meta_media import MediaUnavailable, download, media_url
from app.performance_observation_repository import observations_for_comparison
from app.video_repository import read_analysis
from intelligence.observation_adapter import latest_observations_for_cohort, to_stage61_record
from intelligence.performance_comparison import compare, metric_definition
from intelligence.performance_reasoning import evidence_summary, reason
from intelligence.cross_video_content import construct_groups, prepare_case, run_one_pass
from intelligence.creative_hypotheses import deterministic_baseline, run_one_call

METRICS = frozenset({"ctr", "cpc", "cpm", "impressions"})
WINDOWS = ["7d_click", "1d_view"]
MODEL_META = ("model", "elapsed_seconds", "input_tokens", "output_tokens")


def _base(metric_id, definition, start, stop):
    return {"metric": definition, "cohort": {"date_start": start.isoformat(),
            "date_stop": stop.isoformat(), "placement_scope": "meta_all_placements",
            "report_context": {"action_report_time": "impression",
                               "attribution_windows": WINDOWS}, "peer_count": 0},
            "performance": None, "content_differences": [], "hypotheses": [],
            "abstentions": [], "limitations": [],
            "provenance": {"model_calls": 0}}


def _readable_citations(rows, packets):
    """Attach only text already present in a validated, bounded evidence packet."""
    catalog = {entry["ref"]: entry for packet in packets
               for kind in ("transcript", "ocr") for entry in packet[kind]}
    return [{**row, **({"excerpt": catalog[row["evidence_ref"]]["text"]}
                     if row["evidence_ref"] in catalog else {})} for row in rows]


def _readable_differences(rows, packets):
    return [{**row, "evidence_refs": _readable_citations(row["evidence_refs"], packets),
             "counterexamples": _readable_citations(row["counterexamples"], packets)} for row in rows]


def _content(db, company_id, connection_id, account_uuid, selected):
    """Only a unique, explicit ad-to-video asset edge may supply raw content."""
    analyses, assets = {}, {}
    for member in selected:
        provider_id = member["provider_id"]
        rows = db.execute("""SELECT asset.id,asset.external_id,asset.video_id,
                    asset.analysis_state,asset.analysis_version,asset.connection_id,
                    asset.platform,account.external_id AS account_external_id
            FROM company_ad_assignments assignment
            JOIN meta_library_items ad ON ad.id=assignment.ad_item_id
              AND ad.connection_id=assignment.connection_id
              AND ad.account_id=assignment.account_id
            JOIN meta_ad_assets edge ON edge.ad_item_id=ad.id
            JOIN meta_library_items asset ON asset.id=edge.video_item_id
              AND asset.connection_id=ad.connection_id
            JOIN meta_accounts account ON account.id=asset.account_id
            WHERE assignment.company_id=%s AND assignment.connection_id=%s
              AND assignment.account_id=%s AND ad.external_id=%s
              AND ad.content_type='ad' AND asset.content_type='video'""",
            (company_id, connection_id, account_uuid, provider_id)).fetchall()
        if len(rows) != 1:
            return None, None, "ambiguous_or_missing_video_asset"
        asset = rows[0]
        if (asset["analysis_state"] != "completed" or asset["video_id"] is None
                or asset["analysis_version"] != library.ANALYSIS_VERSION):
            return None, None, "video_analysis_unavailable"
        analysis = read_analysis(db, asset["video_id"], connection_id=connection_id)
        if not analysis or not analysis.get("scenes") or not analysis.get("metadata", {}).get("duration_seconds"):
            return None, None, "malformed_or_missing_video_evidence"
        analyses[provider_id] = analysis
        assets[provider_id] = asset
    return analyses, assets, None


def generate(user, company_id, account_id, metric_id, start: date, stop: date,
             *, compare_content=run_one_pass, propose=run_one_call):
    if metric_id not in METRICS:
        raise HTTPException(422, "Unsupported intelligence metric.")
    definition = metric_definition(metric_id, "meta_ads")
    result = _base(metric_id, definition, start, stop)
    started = perf_counter()
    with library.database() as db, db.transaction():
        company = authorize(db, user, company_id)
        if company["connection_id"] is None:
            result["abstentions"].append("meta_disconnected")
            return result
        account = db.execute("""SELECT a.id,a.external_id,c.status,c.expires_at,
                   c.id AS connection_id,c.token_ciphertext
            FROM company_accounts ca JOIN meta_accounts a ON a.id=ca.account_id
              AND a.connection_id=ca.connection_id
            JOIN meta_connections c ON c.id=ca.connection_id
            WHERE ca.company_id=%s AND ca.account_id=%s AND ca.connection_id=%s
              AND a.platform='meta_ads'""",
            (company_id, account_id, company["connection_id"])).fetchone()
        if account is None:
            raise HTTPException(404, "Company Meta account was not found.")
        if account["status"] != "connected" or account["expires_at"] <= library.now():
            result["abstentions"].append("meta_disconnected")
            return result
    # The repository's exact-context query requires the account currency.
    return _finish(user, company_id, account, metric_id, start, stop, result, started,
                   compare_content, propose)


def _finish(user, company_id, account, metric_id, start, stop, result, started,
            compare_content, propose):
    with library.database() as db, db.transaction():
        company = authorize(db, user, company_id, connection_id=account["connection_id"])
        if company["connection_id"] != account["connection_id"]:
            raise HTTPException(409, "Company Meta connection changed; retry the request.")
        currencies = db.execute("""SELECT DISTINCT o.account_currency FROM performance_observations o
            JOIN company_ad_assignments x ON x.company_id=o.company_id AND x.ad_item_id=o.item_uuid
              AND x.connection_id=o.connection_id AND x.account_id=o.account_uuid
            WHERE o.company_id=%s AND o.connection_id=%s AND o.account_uuid=%s
              AND o.provider_account_id=%s AND o.source='meta_ads'
              AND o.placement_scope='meta_all_placements' AND o.report_start=%s
              AND o.report_end=%s AND o.action_report_time='impression'
              AND o.attribution_windows=%s ORDER BY o.account_currency""",
            (company_id, account["connection_id"], account["id"], account["external_id"],
             start, stop, WINDOWS)).fetchall()
    if len(currencies) != 1:
        result["abstentions"].append("insufficient_or_mixed_report_context")
        return result
    currency = currencies[0]["account_currency"]
    observations = observations_for_comparison(user, company_id, source="meta_ads",
        provider_account_id=account["external_id"], placement_scope="meta_all_placements",
        report_start=start, report_end=stop, action_report_time="impression",
        attribution_windows=WINDOWS, account_currency=currency)
    with library.database() as db, db.transaction():
        company = authorize(db, user, company_id, connection_id=account["connection_id"])
        if company["connection_id"] != account["connection_id"]:
            raise HTTPException(409, "Company Meta connection changed; retry the request.")
        owned = {row["ad_item_id"] for row in db.execute("""SELECT ad_item_id
            FROM company_ad_assignments WHERE company_id=%s AND connection_id=%s
              AND account_id=%s""", (company_id, account["connection_id"], account["id"])).fetchall()}
        observations = [row for row in observations if row["item_uuid"] in owned
                        and row["account_uuid"] == account["id"]
                        and row["connection_id"] == account["connection_id"]]
        latest = latest_observations_for_cohort(observations)
        try:
            records = [to_stage61_record(row) for row in latest]
        except (ValueError, KeyError, TypeError):
            result["abstentions"].append("malformed_stored_observation")
            return result
        result["cohort"].update({"account_id": str(account["id"]), "currency": currency,
                                  "observation_count": len(observations),
                                  "distinct_ads": len(records)})
        if len(records) < 6:
            result["abstentions"].append("insufficient_historical_cohort")
            return result
        report = None
        try:
            # A missing metric on the first ad must not hide a valid cohort.
            for row in records:
                candidate = compare(row, [other for other in records if other is not row],
                                    [metric_id])
                report = candidate
                if candidate["metric_comparisons"][0]["eligibility"]:
                    break
        except (ValueError, KeyError, TypeError):
            result["abstentions"].append("malformed_stored_observation")
            return result
        metric = report["metric_comparisons"][0]
        result["cohort"]["peer_count"] = metric["sample_size"]
        if not metric["eligibility"]:
            result["abstentions"].extend(metric["abstention_reasons"])
            return result
        result["performance"] = {**reason(report),
                                  "metric_facts": evidence_summary(report)["metrics"][0]}
        result["limitations"].extend(result["performance"]["limitations"])
        try:
            groups = construct_groups(report, metric_id)
        except ValueError as error:
            result["abstentions"].append("content_group_unavailable")
            result["limitations"].append(str(error))
            return result
        selected = groups["higher_metric_group"] + groups["lower_metric_group"]
        result["cohort"]["content_groups"] = {
            "higher": groups["higher_metric_group"],
            "lower": groups["lower_metric_group"],
            "middle_excluded_count": groups["middle_excluded_count"]}
        analyses, assets, gap = _content(db, company_id, account["connection_id"], account["id"], selected)
    if gap:
        result["abstentions"].append("insufficient_source_video_coverage")
        result["limitations"].append(gap)
        return result
    try:
        client = library.connection_client(account)
        with TemporaryDirectory(prefix="company-intelligence-") as directory:
            paths = {}
            download_started = perf_counter()
            for index, member in enumerate(selected):
                provider_id = member["provider_id"]
                destination = Path(directory, f"source-{index}.mp4")
                download(media_url(client, assets[provider_id]), destination)
                paths[provider_id] = destination
            result["provenance"]["media_download_seconds"] = round(perf_counter() - download_started, 3)
            case = prepare_case(report, metric_id, analyses, paths)
            if any(not packet["frames"] for packet in case["packets"]):
                result["abstentions"].append("insufficient_source_video_coverage")
                return result
    except (MediaUnavailable, meta.MetaError, OSError) as error:
        result["abstentions"].append("source_media_unavailable")
        result["limitations"].append(type(error).__name__)
        return result
    except Exception as error:
        result["abstentions"].append("malformed_stored_evidence")
        result["limitations"].append(type(error).__name__)
        return result
    try:
        result["provenance"]["model_calls"] = 1
        differences = compare_content(case)
    except Exception as error:
        result["abstentions"].append("content_model_or_validation_failed")
        result["limitations"].append(type(error).__name__)
        return result
    result["content_differences"] = _readable_differences(differences["observed_differences"], case["packets"])
    result["limitations"].extend(differences["limitations"])
    result["provenance"]["model_responses"] = [
        {key: value for key, value in item.items() if key in MODEL_META}
        for item in differences["provenance"]["model_responses"]]
    result["provenance"]["elapsed_seconds"] = round(perf_counter() - started, 3)
    if not differences["observed_differences"]:
        result["abstentions"].append("no_actionable_content_differences")
        return result
    try:
        if not deterministic_baseline(differences, report)["hypotheses"]:
            result["abstentions"].append("no_actionable_content_differences")
            return result
        result["provenance"]["model_calls"] = 2
        hypotheses = propose(differences, report)
    except Exception as error:
        result["abstentions"].append("hypothesis_model_or_validation_failed")
        result["limitations"].append(type(error).__name__)
        result["provenance"]["model_calls"] = 2
        return result
    result["hypotheses"] = [{**row,
        "evidence_refs": _readable_citations(row["evidence_refs"], case["packets"]),
        "counterevidence": _readable_citations(row["counterevidence"], case["packets"])}
        for row in hypotheses["hypotheses"][:3]]
    result["provenance"]["model_calls"] = 1 + hypotheses["provenance"]["model_calls"]
    result["provenance"]["elapsed_seconds"] = round(perf_counter() - started, 3)
    model_meta = hypotheses["provenance"].get("model_response")
    if model_meta:
        result["provenance"]["model_responses"].append(
            {key: value for key, value in model_meta.items() if key in MODEL_META})
    return result
