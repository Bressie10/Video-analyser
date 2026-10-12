"""Company-authorized, append-only provider history. No comparison scoring."""

from datetime import date
from hashlib import sha256
import json

from psycopg.types.json import Jsonb

from app import meta_library_repository as library
from app.company_authorization import authorize
from app.video_repository import save_performance

SCHEMA_VERSION = "v9-stage6.3-1"


class ObservationOwnershipError(LookupError):
    pass


def _assigned_ad(db, user, company_id, connection_id, item_id, *, write):
    company = authorize(db, user, company_id, write=write, connection_id=connection_id)
    if company["connection_id"] != connection_id:
        raise ObservationOwnershipError("Ad is not assigned to this company.")
    row = db.execute("""SELECT i.external_id AS ad_id,a.external_id AS account_id,
                             i.account_id AS account_uuid,i.id AS item_uuid,i.video_id
        FROM company_ad_assignments x JOIN meta_library_items i ON i.id=x.ad_item_id
          AND i.connection_id=x.connection_id AND i.account_id=x.account_id
        JOIN meta_accounts a ON a.id=i.account_id AND a.connection_id=i.connection_id
        WHERE x.company_id=%s AND x.connection_id=%s AND x.ad_item_id=%s
          AND a.platform='meta_ads' AND i.content_type='ad'
        FOR SHARE OF x,i,a""", (company_id, connection_id, item_id)).fetchone()
    if row is None:
        raise ObservationOwnershipError("Ad is not assigned to this company.")
    return row


def authorized_ad(user, company_id, connection_id, item_id):
    """Authorize before the provider call; writer repeats this under transaction locks."""
    with library.database() as db, db.transaction():
        return _assigned_ad(db, user, company_id, connection_id, item_id, write=False)


def _context_key(company_id, ad_id, account_id, details):
    context = (str(company_id), "meta_ads", "ad", ad_id, account_id,
               "meta_all_placements", details["date_start"], details["date_stop"],
               details["account_currency"], details["action_report_time"],
               details["action_attribution_windows"])
    return sha256(json.dumps(context, separators=(",", ":")).encode()).hexdigest()


def save_meta_ad_observation(user, company_id, connection_id, item_id,
                             provider_identity, performance):
    """Each successful fetch adds a version. A video snapshot updates in the same transaction."""
    details = performance["performance_metrics"]["meta_ads"]
    if (provider_identity.get("placement_scope") != "meta_all_placements"
            or details.get("action_report_time") != "impression"
            or details.get("action_attribution_windows") != ["7d_click", "1d_view"]
            or not details.get("account_currency")):
        raise ValueError("Incomplete Meta observation context.")
    with library.database() as db, db.transaction():
        assigned = _assigned_ad(db, user, company_id, connection_id, item_id, write=True)
        if (assigned["ad_id"] != provider_identity.get("ad_id")
                or assigned["account_id"] != "act_" + str(provider_identity.get("account_id"))):
            raise ObservationOwnershipError("Provider identity does not match assigned ad.")
        # The ad item may have no direct ContentMetric video. Shared creative assets
        # are deliberately not treated as an ad-specific current snapshot.
        video_id = assigned["video_id"]
        if video_id is not None and not save_performance(video_id, performance, connection=db):
            raise ObservationOwnershipError("Associated video is unavailable.")
        row = db.execute("""INSERT INTO performance_observations
            (company_id,connection_id,account_uuid,item_uuid,video_id,source,
             provider_object_type,provider_object_id,provider_account_id,
             placement_scope,exposure_type,report_start,report_end,account_currency,
             action_report_time,attribution_windows,metric_payload,provenance,context_key)
            VALUES (%s,%s,%s,%s,%s,'meta_ads','ad',%s,%s,'meta_all_placements','paid',
                    %s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id,fetched_at""",
            (company_id, connection_id, assigned["account_uuid"], item_id, video_id,
             provider_identity["ad_id"], assigned["account_id"],
             date.fromisoformat(details["date_start"]), date.fromisoformat(details["date_stop"]),
             details["account_currency"], details["action_report_time"],
             details["action_attribution_windows"], Jsonb(details),
             Jsonb({"schema_version": SCHEMA_VERSION, "identity_verified": True,
                    "reporting_granularity": "ad_all_days"}),
             _context_key(company_id, provider_identity["ad_id"], assigned["account_id"], details)),
        ).fetchone()
    return row


def observations_for_comparison(user, company_id, *, source, provider_account_id,
                                placement_scope, report_start, report_end,
                                action_report_time, attribution_windows,
                                account_currency=None):
    """Exact-context, deterministic authorized rows; no cross-company fallback."""
    with library.database() as db, db.transaction():
        authorize(db, user, company_id)
        return db.execute("""SELECT o.* FROM performance_observations o
            WHERE o.company_id=%s AND o.source=%s AND o.provider_account_id=%s
              AND o.placement_scope=%s AND o.report_start=%s AND o.report_end=%s
              AND o.action_report_time IS NOT DISTINCT FROM %s
              AND o.attribution_windows=%s
              AND o.account_currency IS NOT DISTINCT FROM %s
            ORDER BY o.provider_object_id,o.fetched_at DESC,o.id""",
            (company_id, source, provider_account_id, placement_scope, report_start,
             report_end, action_report_time, attribution_windows, account_currency)).fetchall()
