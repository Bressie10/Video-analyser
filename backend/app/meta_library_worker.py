"""Small PostgreSQL-backed scheduler: one analysis slot and two I/O slots."""

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.json import Jsonb

from app import facebook, instagram, meta, meta_ads
from app import meta_library_repository as repo
from app.analysis_pipeline import analyze_file
from app.meta_library_discovery import discover
from app.meta_library_metrics import organic_performance
from app.meta_media import MediaUnavailable, download, media_url
from app.video_processing import VideoProcessingError
from app.video_repository import save_analysis

logger = logging.getLogger(__name__)
LOCK_BASE = 72419300


def schedule():
    with repo.database() as db:
        db.execute(
            "UPDATE meta_connections SET status='reconnect_required' WHERE status='connected' AND expires_at<=now()"
        )
        db.execute("""UPDATE meta_jobs j SET state='blocked',error='Reconnect Meta to continue.'
            FROM meta_connections c WHERE j.connection_id=c.id AND c.status='reconnect_required' AND j.state='queued'""")
        rows = db.execute(
            "SELECT id FROM meta_connections WHERE status='connected' AND next_sync_at<=now() FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for row in rows:
            repo.enqueue_sync(db, row["id"])
        repo.finalize_runs(db)


def claim_job(analysis=False):
    with repo.database() as db:
        job = db.execute(
            """SELECT j.* FROM meta_jobs j JOIN meta_connections c ON c.id=j.connection_id
            WHERE c.status='connected' AND c.expires_at>now() AND (j.kind='analysis')=%s
            AND ((j.state='queued' AND j.available_at<=now()) OR (j.state='running' AND j.lease_until<now()))
            ORDER BY j.available_at,j.created_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            (analysis,),
        ).fetchone()
        if not job:
            return None
        claim = uuid4()
        db.execute(
            "UPDATE meta_jobs SET state='running',attempts=attempts+1,claim=%s,lease_until=now()+interval '2 minutes' WHERE id=%s",
            (claim, job["id"]),
        )
        return {**job, "claim": claim, "attempts": job["attempts"] + 1}


def finish(job, state="completed", error=None, payload=None, delay=0):
    with repo.database() as db:
        db.execute(
            """UPDATE meta_jobs SET state=%s,error=%s,payload=COALESCE(%s,payload),available_at=%s,
            attempts=CASE WHEN %s THEN 0 ELSE attempts END, lease_until=NULL WHERE id=%s AND claim=%s AND state='running'""",
            (
                state,
                error,
                Jsonb(payload) if payload is not None else None,
                repo.now() + timedelta(seconds=delay),
                payload is not None,
                job["id"],
                job["claim"],
            ),
        )


def heartbeat(job, done):
    while not done.wait(20):
        try:
            with repo.database() as db:
                db.execute(
                    "UPDATE meta_jobs SET lease_until=now()+interval '2 minutes' WHERE id=%s AND claim=%s AND state='running'",
                    (job["id"], job["claim"]),
                )
        except Exception:
            logger.warning("Meta worker heartbeat unavailable.")


def item_status(item_id, field, state, error=None):
    # field is selected only by this module, never by a request.
    from psycopg import sql

    status_column = "analysis_state" if field == "analysis" else "metrics_state"
    error_column = "analysis_error" if field == "analysis" else "metrics_error"
    with repo.database() as db:
        db.execute(
            sql.SQL("UPDATE meta_library_items SET {}=%s,{}=%s WHERE id=%s").format(
                sql.Identifier(status_column), sql.Identifier(error_column)
            ),
            (state, error, item_id),
        )


def analyze(job, client, item):
    if item["video_id"] and item["analysis_version"] == repo.ANALYSIS_VERSION:
        finish(job, "reused")
        return
    item_status(item["id"], "analysis", "processing")
    with TemporaryDirectory(prefix="meta-video-") as directory:
        source = Path(directory, "source.mp4")
        download(media_url(client, item), source)
        analysis = analyze_file(source, directory, allow_silent=True)
    with repo.database() as db:
        # Fence a stale worker and prevent writes following disconnection.
        current = db.execute(
            """SELECT j.id FROM meta_jobs j JOIN meta_connections c ON c.id=j.connection_id
            WHERE j.id=%s AND j.claim=%s AND j.state='running' AND c.status='connected'
            FOR UPDATE OF j,c""",
            (job["id"], job["claim"]),
        ).fetchone()
        if not current:
            return
        save_analysis(
            analysis,
            connection=db,
            video_id=item["id"],
            analysis_version=repo.ANALYSIS_VERSION,
            connection_id=job["connection_id"],
        )
        db.execute(
            """UPDATE meta_library_items SET video_id=id,analysis_version=%s,
            analysis_state='completed',analysis_error=NULL WHERE id=%s""",
            (repo.ANALYSIS_VERSION, item["id"]),
        )
        db.execute(
            "UPDATE meta_jobs SET state='completed',error=NULL,lease_until=NULL WHERE id=%s",
            (job["id"],),
        )


def refresh(job, client, item):
    if not job["payload"].get("manual") and not repo.recent(item["published_at"]):
        item_status(item["id"], "metrics", "retained")
        finish(job, "reused")
        return
    if item["content_type"] == "ad":
        if item["published_at"] is None:
            raise meta_ads.AdMetricsUnavailable("Ad creation date is unknown.")
        try:
            tz = ZoneInfo(item["timezone_name"])
        except ZoneInfoNotFoundError:
            raise meta_ads.AdMetricsUnavailable(
                "Ad account reporting timezone is unavailable."
            ) from None
        until = repo.now().astimezone(tz).date()
        since = item["published_at"].astimezone(tz).date()
        performance = meta_ads.ad_performance(client, item["external_id"], since, until)
    elif item["platform"] == "instagram" or (
        item["platform"] == "facebook" and item["account_external_id"].isdigit()
    ):
        performance = organic_performance(client, item)
    else:
        raise meta_ads.AdMetricsUnavailable(
            "Only associated ad metrics are available for this asset."
        )
    with repo.database() as db:
        active = db.execute(
            """SELECT j.id FROM meta_jobs j JOIN meta_connections c ON c.id=j.connection_id
            WHERE j.id=%s AND j.claim=%s AND j.state='running' AND c.status='connected' FOR UPDATE OF j,c""",
            (job["id"], job["claim"]),
        ).fetchone()
        if active:
            db.execute(
                """INSERT INTO meta_library_performance(item_id,snapshot) VALUES (%s,%s)
                ON CONFLICT(item_id) DO UPDATE SET snapshot=EXCLUDED.snapshot,fetched_at=now()""",
                (item["id"], Jsonb(performance)),
            )
            db.execute(
                "UPDATE meta_library_items SET metrics_state='current',metrics_error=NULL WHERE id=%s",
                (item["id"],),
            )
    finish(job)


def follow(job):
    with repo.database() as db:
        target = db.execute(
            """SELECT * FROM meta_jobs WHERE item_id=%s AND kind=%s ORDER BY created_at DESC LIMIT 1""",
            (job["payload"]["follow_item"], job["kind"]),
        ).fetchone()
    if target and target["state"] in ("queued", "running", "blocked"):
        finish(job, "queued", delay=10)
    else:
        finish(
            job,
            target["state"] if target else "failed",
            target["error"] if target else "Original task is unavailable.",
        )


def process_job(job):
    done = threading.Event()
    pulse = threading.Thread(target=heartbeat, args=(job, done), daemon=True)
    pulse.start()
    try:
        if job["payload"].get("follow_item"):
            follow(job)
            return
        with repo.database() as db:
            connection = db.execute(
                "SELECT * FROM meta_connections WHERE id=%s", (job["connection_id"],)
            ).fetchone()
            item = (
                repo.item_with_account(db, job["item_id"]) if job["item_id"] else None
            )
        client = repo.connection_client(connection)
        if job["kind"] == "discovery":
            payload = discover(job, client)
            finish(job, "queued" if payload else "completed", payload=payload)
        elif job["kind"] == "analysis":
            analyze(job, client, item)
        else:
            refresh(job, client, item)
    except meta.MetaNotConnected:
        with repo.database() as db:
            db.execute(
                "UPDATE meta_connections SET status='reconnect_required' WHERE id=%s AND status='connected'",
                (job["connection_id"],),
            )
        finish(job, "blocked", "Reconnect Meta to continue.")
    except (MediaUnavailable, meta.MetaPermissionError) as error:
        message = (
            "Media is unavailable or access is not permitted."
            if job["kind"] == "analysis"
            else "Meta access is not permitted."
        )
        if isinstance(error, MediaUnavailable):
            message = str(error)
        if job["item_id"]:
            item_status(job["item_id"], job["kind"], "unavailable", message)
        finish(job, "unavailable", message)
    except (
        VideoProcessingError,
        instagram.NotInstagramReel,
        instagram.InstagramMetricsUnavailable,
        facebook.InvalidFacebookVideo,
        facebook.FacebookMetricsUnavailable,
        meta_ads.AdMetricsUnavailable,
    ):
        state = "unsupported" if job["kind"] == "analysis" else "unavailable"
        message = (
            "Video processing could not complete."
            if job["kind"] == "analysis"
            else "Metrics are unavailable for this item."
        )
        if job["item_id"]:
            item_status(job["item_id"], job["kind"], state, message)
        finish(job, state, message)
    except Exception:
        # Never log provider response bodies, URLs, tokens, or media text.
        retry = job["attempts"] < 3
        message = (
            "Temporary processing failure."
            if retry
            else "Processing failed after three attempts."
        )
        if job["item_id"]:
            item_status(
                job["item_id"], job["kind"], "queued" if retry else "failed", message
            )
        finish(
            job,
            "queued" if retry else "failed",
            message,
            delay=30 * 2 ** (job["attempts"] - 1),
        )
        logger.warning("Meta job failed (%s).", job["kind"])
    finally:
        done.set()
        pulse.join(timeout=1)


def worker(stop, slot):
    while not stop.is_set():
        try:
            with repo.database() as lock_db:
                locked = lock_db.execute(
                    "SELECT pg_try_advisory_lock(%s) AS acquired", (LOCK_BASE + slot,)
                ).fetchone()["acquired"]
                lock_db.commit()
                if not locked:
                    stop.wait(5)
                    continue
                try:
                    while not stop.is_set():
                        if slot == 1:
                            schedule()
                        job = claim_job(analysis=slot == 0)
                        if job:
                            process_job(job)
                        else:
                            stop.wait(2)
                finally:
                    lock_db.execute(
                        "SELECT pg_advisory_unlock(%s)", (LOCK_BASE + slot,)
                    )
        except Exception:
            logger.warning("Meta worker database/configuration unavailable.")
            stop.wait(5)


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    threads = []
    if os.environ.get("META_TOKEN_ENCRYPTION_KEY") and os.environ.get("DATABASE_URL"):
        repo.cipher()  # Fail closed on an invalid encryption key.
        if os.environ.get("META_WORKER_ENABLED", "true").lower() == "true":
            for slot in range(3):
                thread = threading.Thread(
                    target=worker,
                    args=(stop, slot),
                    daemon=True,
                    name=f"meta-worker-{slot}",
                )
                thread.start()
                threads.append(thread)
    try:
        yield
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
