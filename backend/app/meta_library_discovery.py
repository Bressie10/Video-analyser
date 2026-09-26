"""Resumable Graph discovery. Provider IDs and cursors stay behind the API."""

import re
from datetime import datetime, timezone

from app import meta
from app import meta_library_repository as repo


def identifier(value, account=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"act_[0-9]{1,30}" if account else r"[0-9]{1,30}", value
    ):
        raise meta.MetaError("Invalid source identity.")
    return value


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def label(row, default):
    return next(
        (
            row[k].strip()[:200]
            for k in ("name", "title", "caption", "description", "username")
            if isinstance(row.get(k), str) and row[k].strip()
        ),
        default,
    )


def page(client, path, fields, after=None):
    params = {"fields": fields, "limit": 100}
    if after:
        params["after"] = after
    result = client.get(path, params)
    rows, paging = result.get("data"), result.get("paging", {})
    if (
        not isinstance(rows, list)
        or any(not isinstance(r, dict) for r in rows)
        or not isinstance(paging, dict)
    ):
        raise meta.MetaError("Invalid discovery page.")
    cursor = None
    if paging.get("next"):
        cursors = paging.get("cursors")
        cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor) > 2048
            or cursor == after
        ):
            raise meta.MetaError("Invalid discovery cursor.")
    return rows, cursor


def discovery_task(db, job, edge, account=None):
    payload = {"edge": edge}
    if account:
        payload["account_id"] = str(account["id"])
    key = edge + (":" + str(account["id"]) if account else "")
    repo.add_job(db, job["run_id"], job["connection_id"], "discovery", key, payload)


def eligible_item(db, job, account, item):
    # initialized_at is a fixed baseline, not the last sync time: late discovery
    # of a new publication is eligible; an old backfill never drains the backlog.
    if (
        account["initialized_at"]
        and item["published_at"]
        and item["published_at"] > account["initialized_at"]
        and repo.recent(item["published_at"])
    ):
        db.execute(
            "UPDATE meta_library_items SET auto_analyze=true WHERE id=%s", (item["id"],)
        )
        item["auto_analyze"] = True
    repo.queue_analysis(db, job["run_id"], item)
    if repo.recent(item["published_at"]) and (
        item["content_type"] == "ad" or account["platform"] != "meta_ads"
    ):
        repo.add_job(
            db,
            job["run_id"],
            job["connection_id"],
            "metrics",
            item["id"],
            item_id=item["id"],
        )


def creative_video_ids(creative):
    """Return explicit assets only; never infer a video ID from an ad/post ID."""
    if not isinstance(creative, dict):
        return []
    values = [creative.get("video_id")]
    story = creative.get("object_story_spec") or {}
    if isinstance(story, dict):
        video = story.get("video_data") or {}
        if isinstance(video, dict):
            values.append(video.get("video_id"))
    feed = creative.get("asset_feed_spec") or {}
    if isinstance(feed, dict):
        for video in feed.get("videos", []) or []:
            if isinstance(video, dict):
                values.append(video.get("video_id"))
    return sorted({identifier(v) for v in values if v is not None})


def import_ad(db, job, account, row, client):
    ad = repo.upsert_item(
        db,
        account,
        identifier(row.get("id")),
        "ad",
        label(row, "Meta ad"),
        timestamp(row.get("created_time")),
    )
    creative = row.get("creative") or {}
    video_ids = creative_video_ids(creative)
    # Published post creatives may omit video_id; resolve only a provider-supplied post.
    post = (
        creative.get("effective_object_story_id")
        if isinstance(creative, dict)
        else None
    )
    if (
        not video_ids
        and isinstance(post, str)
        and re.fullmatch(r"[0-9]{1,30}_[0-9]{1,30}", post)
    ):
        try:
            story = client.get(
                post, {"fields": "attachments{media_type,target,subattachments}"}
            )
        except meta.MetaNotConnected:
            raise
        except meta.MetaError:
            # Retain the ad and its independent metrics when the post is private.
            story = {}

        def collect(rows):
            for attachment in rows:
                if not isinstance(attachment, dict):
                    continue
                if attachment.get("media_type") == "video" and isinstance(
                    attachment.get("target"), dict
                ):
                    video_ids.append(identifier(attachment["target"].get("id")))
                collect((attachment.get("subattachments") or {}).get("data", []))

        collect((story.get("attachments") or {}).get("data", []))
    links = []
    for external_id in set(video_ids):
        # Video identity is Facebook's video namespace even when found via an ad.
        asset_account = {**account, "platform": "facebook"}
        item = repo.upsert_item(
            db, asset_account, external_id, "video", label(row, "Ad video"), None
        )
        links.append(item["id"])
        db.execute(
            "INSERT INTO meta_ad_assets VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (ad["id"], item["id"]),
        )
        # Resolve publication metadata separately. Missing access must not lose the ad.
        discovery_task_for_asset(db, job, account, item)
    db.execute(
        "DELETE FROM meta_ad_assets WHERE ad_item_id=%s AND NOT(video_item_id=ANY(%s))",
        (ad["id"], links),
    )
    if not links:
        db.execute(
            "UPDATE meta_library_items SET analysis_state='unavailable',analysis_error='No accessible video creative.' WHERE id=%s",
            (ad["id"],),
        )
    else:
        db.execute(
            "UPDATE meta_library_items SET analysis_state='discovered',analysis_error=NULL WHERE id=%s",
            (ad["id"],),
        )
    eligible_item(db, job, account, ad)


def discovery_task_for_asset(db, job, account, item):
    repo.add_job(
        db,
        job["run_id"],
        job["connection_id"],
        "discovery",
        "asset:" + str(item["id"]),
        {
            "edge": "asset",
            "account_id": str(account["id"]),
            "asset_id": str(item["id"]),
        },
    )


def discover(job, client):
    payload = job["payload"]
    edge = payload["edge"]
    with repo.database() as db:
        account = (
            db.execute(
                "SELECT * FROM meta_accounts WHERE id=%s", (payload["account_id"],)
            ).fetchone()
            if payload.get("account_id")
            else None
        )
    after = payload.get("after")
    if edge == "instagram_account":
        result = client.for_page(account["external_id"]).get(
            account["external_id"],
            {"fields": "instagram_business_account{id,name,username}"},
        )
        linked = result.get("instagram_business_account")
        rows, cursor = ([linked] if linked else []), None
    elif edge == "asset":
        with repo.database() as db:
            item = repo.item_with_account(db, payload["asset_id"])
        try:
            result = client.get(
                item["external_id"], {"fields": "id,created_time,title"}
            )
        except meta.MetaNotConnected:
            raise
        except meta.MetaError:
            with repo.database() as db:
                db.execute(
                    """UPDATE meta_library_items SET analysis_state='unavailable',
                    analysis_error='Meta does not provide access to this video asset.'
                    WHERE id=%s AND video_id IS NULL""",
                    (item["id"],),
                )
            raise
        if identifier(result.get("id")) != item["external_id"]:
            raise meta.MetaError("Unexpected video identity.")
        with repo.database() as db:
            db.execute(
                "UPDATE meta_library_items SET published_at=COALESCE(published_at,%s) WHERE id=%s",
                (timestamp(result.get("created_time")), item["id"]),
            )
            item = repo.item_with_account(db, item["id"])
            eligible_item(db, job, account, item)
        return None
    elif edge == "pages":
        rows, cursor = page(client, "me/accounts", "id,name", after)
    elif edge == "ad_accounts":
        rows, cursor = page(client, "me/adaccounts", "id,name,timezone_name", after)
    elif edge == "instagram":
        rows, cursor = page(
            client,
            f"{account['external_id']}/media",
            "id,caption,media_type,media_product_type,timestamp",
            after,
        )
    elif edge in ("videos", "reels"):
        rows, cursor = page(
            client.for_page(account["external_id"]),
            f"{account['external_id']}/{'video_reels' if edge == 'reels' else 'videos'}",
            "id,title,description,created_time",
            after,
        )
    elif edge == "ads":
        rows, cursor = page(
            client,
            f"{account['external_id']}/ads",
            "id,name,created_time,creative{id,video_id,object_story_spec,asset_feed_spec,effective_object_story_id}",
            after,
        )
    else:
        raise meta.MetaError("Unsupported discovery task.")
    for index, row in enumerate(rows):
        try:
            with repo.database() as db:
                if edge in ("pages", "ad_accounts", "instagram_account"):
                    platform = {
                        "pages": "facebook",
                        "ad_accounts": "meta_ads",
                        "instagram_account": "instagram",
                    }[edge]
                    discovered = repo.upsert_account(
                        db,
                        job["connection_id"],
                        job["run_id"],
                        platform,
                        identifier(row.get("id"), edge == "ad_accounts"),
                        label(row, platform),
                        account["external_id"] if edge == "instagram_account" else None,
                        row.get("timezone_name") or "UTC",
                    )
                    for child in {
                        "pages": ("videos", "reels", "instagram_account"),
                        "ad_accounts": ("ads",),
                        "instagram_account": ("instagram",),
                    }[edge]:
                        discovery_task(db, job, child, discovered)
                elif edge == "ads":
                    import_ad(db, job, account, row, client)
                else:
                    if edge == "instagram" and row.get("media_type") != "VIDEO":
                        continue
                    kind = (
                        "reel"
                        if edge == "reels" or row.get("media_product_type") == "REELS"
                        else "video"
                    )
                    item = repo.upsert_item(
                        db,
                        account,
                        identifier(row.get("id")),
                        kind,
                        label(row, "Video"),
                        timestamp(row.get("timestamp") or row.get("created_time")),
                    )
                    # An organic discovery upgrades an asset initially seen through Ads.
                    if item["account_id"] != account["id"]:
                        db.execute(
                            "UPDATE meta_library_items SET account_id=%s WHERE id=%s",
                            (account["id"], item["id"]),
                        )
                    eligible_item(db, job, account, item)
        except meta.MetaNotConnected:
            raise
        except (meta.MetaError, ValueError, TypeError):
            # Keep a visible per-row outcome without persisting raw provider messages.
            with repo.database() as db:
                key = f"row:{job['id']}:{payload.get('page_number', 0)}:{index}"
                failure = repo.add_job(
                    db,
                    job["run_id"],
                    job["connection_id"],
                    "discovery",
                    key,
                    {"account_id": str(account["id"])} if account else {},
                )
                if failure:
                    db.execute(
                        "UPDATE meta_jobs SET state='failed',error='Could not import a discovered item.' WHERE id=%s",
                        (failure["id"],),
                    )
    if cursor:
        seen = payload.get("seen_cursors", [])
        if cursor in seen:
            raise meta.MetaError("Repeated discovery cursor.")
        return {
            **payload,
            "after": cursor,
            "seen_cursors": [*seen, cursor],
            "page_number": payload.get("page_number", 0) + 1,
        }
    return None
