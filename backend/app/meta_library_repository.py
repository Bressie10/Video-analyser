"""Private source identity, durable work, and public library projections."""

import hashlib
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import meta
from app.video_repository import _database_url

ANALYSIS_VERSION = 1
INITIAL_LIMIT = 25
RECENT_DAYS = 90


def now():
    return datetime.now(timezone.utc)


def recent(published_at, at=None):
    at = at or now()
    return (
        published_at is not None
        and at - timedelta(days=RECENT_DAYS) < published_at <= at
    )


@contextmanager
def database():
    with psycopg.connect(
        _database_url(), connect_timeout=3, row_factory=dict_row
    ) as db:
        yield db


def cipher():
    from cryptography.fernet import Fernet

    try:
        return Fernet(os.environ.get("META_TOKEN_ENCRYPTION_KEY", "").encode())
    except (ValueError, TypeError):
        raise meta.MetaConfigurationError(
            "Meta credential encryption is not configured."
        ) from None


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def connect_identity(external_id, token, previous=None):
    encrypted = cipher().encrypt(token.access_token.encode()).decode()
    session = secrets.token_urlsafe(32)
    expires = datetime.fromtimestamp(token.expires_at, timezone.utc)
    with database() as db:
        row = db.execute(
            """INSERT INTO meta_connections(external_user_id,token_ciphertext,expires_at)
            VALUES (%s,%s,%s) ON CONFLICT(external_user_id) DO UPDATE SET
            token_ciphertext=EXCLUDED.token_ciphertext, expires_at=EXCLUDED.expires_at,
            status='connected',next_sync_at=now() RETURNING id""",
            (external_id, encrypted, expires),
        ).fetchone()
        connection_id = row["id"]
        if previous:
            db.execute(
                "DELETE FROM meta_sessions WHERE token_hash=%s", (token_hash(previous),)
            )
        db.execute("DELETE FROM meta_sessions WHERE expires_at<=now()")
        db.execute(
            "INSERT INTO meta_sessions VALUES (%s,%s,%s)",
            (token_hash(session), connection_id, expires),
        )
        db.execute(
            "UPDATE meta_jobs SET state='queued',available_at=now(),attempts=0 WHERE connection_id=%s AND state='blocked'",
            (connection_id,),
        )
        run = enqueue_sync(db, connection_id)
    return session, str(run)


def session_connection(session):
    if not session:
        raise meta.MetaNotConnected("Connect Meta again.")
    with database() as db:
        row = db.execute(
            """SELECT c.* FROM meta_connections c JOIN meta_sessions s ON s.connection_id=c.id
            WHERE s.token_hash=%s AND s.expires_at>now() AND c.status='connected' AND c.expires_at>now()""",
            (token_hash(session),),
        ).fetchone()
    if row is None:
        raise meta.MetaNotConnected("Connect Meta again.")
    return row


def connection_client(connection):
    from cryptography.fernet import InvalidToken

    if connection["status"] != "connected" or connection["expires_at"] <= now():
        raise meta.MetaNotConnected("Connect Meta again.")
    try:
        token = cipher().decrypt(connection["token_ciphertext"].encode()).decode()
    except (InvalidToken, AttributeError, UnicodeError):
        raise meta.MetaConfigurationError(
            "Meta credentials cannot be decrypted."
        ) from None
    return meta.MetaClient(
        meta.settings(), meta.UserToken(token, connection["expires_at"].timestamp())
    )


def disconnect(connection_id):
    with database() as db:
        db.execute(
            "UPDATE meta_connections SET status='disconnected',token_ciphertext=NULL WHERE id=%s",
            (connection_id,),
        )
        db.execute("DELETE FROM meta_sessions WHERE connection_id=%s", (connection_id,))
        db.execute(
            "UPDATE meta_jobs SET state='cancelled',claim=NULL WHERE connection_id=%s AND state IN ('queued','running','blocked')",
            (connection_id,),
        )
        db.execute(
            "UPDATE meta_sync_runs SET finished_at=now() WHERE connection_id=%s AND finished_at IS NULL",
            (connection_id,),
        )


def add_job(db, run_id, connection_id, kind, key, payload=None, item_id=None):
    return db.execute(
        """INSERT INTO meta_jobs(run_id,connection_id,kind,task_key,payload,item_id)
        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
        (run_id, connection_id, kind, str(key), Jsonb(payload or {}), item_id),
    ).fetchone()


def enqueue_sync(db, connection_id):
    # Serialize creation with scheduling and reconnection.
    db.execute(
        "SELECT id FROM meta_connections WHERE id=%s FOR UPDATE", (connection_id,)
    )
    active = db.execute(
        "SELECT id FROM meta_sync_runs WHERE connection_id=%s AND kind='sync' AND finished_at IS NULL",
        (connection_id,),
    ).fetchone()
    if active:
        return active["id"]
    run = db.execute(
        "INSERT INTO meta_sync_runs(connection_id,kind) VALUES (%s,'sync') RETURNING id",
        (connection_id,),
    ).fetchone()["id"]
    for edge in ("pages", "ad_accounts"):
        add_job(db, run, connection_id, "discovery", edge, {"edge": edge})
    db.execute(
        "UPDATE meta_connections SET next_sync_at=now()+interval '1 day' WHERE id=%s",
        (connection_id,),
    )
    return run


def upsert_account(
    db,
    connection_id,
    run_id,
    platform,
    external_id,
    label,
    page_id=None,
    timezone_name="UTC",
):
    return db.execute(
        """INSERT INTO meta_accounts(connection_id,platform,external_id,label,page_external_id,timezone_name,initial_run_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(connection_id,platform,external_id) DO UPDATE SET
        label=EXCLUDED.label,page_external_id=EXCLUDED.page_external_id,timezone_name=EXCLUDED.timezone_name,
        initial_run_id=CASE WHEN meta_accounts.initialized_at IS NULL THEN EXCLUDED.initial_run_id ELSE meta_accounts.initial_run_id END
        RETURNING *""",
        (connection_id, platform, external_id, label, page_id, timezone_name, run_id),
    ).fetchone()


def upsert_item(db, account, external_id, content_type, label, published_at):
    return db.execute(
        """INSERT INTO meta_library_items(connection_id,account_id,platform,external_id,content_type,label,published_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(connection_id,platform,external_id) DO UPDATE SET
        label=EXCLUDED.label,published_at=COALESCE(EXCLUDED.published_at,meta_library_items.published_at),last_seen_at=now(),
        content_type=CASE WHEN EXCLUDED.content_type='reel' THEN 'reel' ELSE meta_library_items.content_type END
        RETURNING *""",
        (
            account["connection_id"],
            account["id"],
            account["platform"],
            external_id,
            content_type,
            label,
            published_at,
        ),
    ).fetchone()


def queue_analysis(db, run_id, item, explicit=False):
    if item["content_type"] == "ad":
        return "unsupported"
    if item["video_id"] and item["analysis_version"] == ANALYSIS_VERSION:
        return "reused"
    if not explicit and not (item["auto_analyze"] or item["video_id"]):
        return "deferred"
    added = add_job(
        db, run_id, item["connection_id"], "analysis", item["id"], item_id=item["id"]
    )
    if added:
        db.execute(
            "UPDATE meta_library_items SET analysis_state='queued',analysis_error=NULL WHERE id=%s",
            (item["id"],),
        )
    return "queued"


def item_with_account(db, item_id):
    return db.execute(
        """SELECT i.*,a.external_id AS account_external_id,a.page_external_id,a.timezone_name
        FROM meta_library_items i JOIN meta_accounts a ON a.id=i.account_id WHERE i.id=%s""",
        (item_id,),
    ).fetchone()


def finalize_runs(db):
    runs = db.execute("""SELECT r.* FROM meta_sync_runs r WHERE r.finished_at IS NULL AND NOT r.discovery_finalized
        AND NOT EXISTS(SELECT 1 FROM meta_jobs j WHERE j.run_id=r.id AND j.kind='discovery' AND j.state IN ('queued','running','blocked'))
        FOR UPDATE SKIP LOCKED""").fetchall()
    for run in runs:
        # Only initialize accounts whose complete discovery succeeded. A failed account
        # keeps its initial-import boundary until a subsequent sync succeeds.
        accounts = db.execute(
            """SELECT a.* FROM meta_accounts a WHERE a.initial_run_id=%s AND a.initialized_at IS NULL
            AND NOT EXISTS(SELECT 1 FROM meta_jobs j WHERE j.run_id=%s AND j.kind='discovery'
                AND j.payload->>'account_id'=a.id::text
                AND j.payload->>'edge' IN ('videos','reels','instagram','ads')
                AND j.state IN ('failed','cancelled','unavailable','unsupported'))""",
            (run["id"], run["id"]),
        ).fetchall()
        ids = [a["id"] for a in accounts]
        if ids:
            candidates = db.execute(
                """SELECT DISTINCT i.* FROM meta_library_items i
                LEFT JOIN meta_ad_assets aa ON aa.video_item_id=i.id
                LEFT JOIN meta_library_items ad ON ad.id=aa.ad_item_id
                WHERE (i.account_id=ANY(%s) OR ad.account_id=ANY(%s)) AND i.content_type!='ad'
                AND i.published_at>%s AND i.published_at<=%s
                ORDER BY i.published_at DESC,i.id LIMIT %s""",
                (
                    ids,
                    ids,
                    run["created_at"] - timedelta(days=RECENT_DAYS),
                    run["created_at"],
                    INITIAL_LIMIT,
                ),
            ).fetchall()
            for item in candidates:
                db.execute(
                    "UPDATE meta_library_items SET auto_analyze=true WHERE id=%s",
                    (item["id"],),
                )
                queue_analysis(db, run["id"], item, explicit=True)
            db.execute(
                "UPDATE meta_accounts SET initialized_at=%s WHERE id=ANY(%s)",
                (run["created_at"], ids),
            )
            db.execute(
                "UPDATE meta_library_items SET analysis_state='deferred' WHERE account_id=ANY(%s) AND analysis_state='discovered' AND content_type!='ad'",
                (ids,),
            )
        db.execute(
            "UPDATE meta_sync_runs SET discovery_finalized=true WHERE id=%s",
            (run["id"],),
        )
    db.execute("""UPDATE meta_sync_runs r SET finished_at=now() WHERE finished_at IS NULL AND discovery_finalized
        AND NOT EXISTS(SELECT 1 FROM meta_jobs j WHERE j.run_id=r.id AND j.state IN ('queued','running','blocked'))""")


PUBLIC_FIELDS = (
    "id",
    "account_id",
    "platform",
    "content_type",
    "label",
    "published_at",
    "analysis_state",
    "analysis_error",
    "analysis_version",
    "video_id",
    "metrics_state",
    "metrics_error",
)


def public_item(row):
    return {key: row[key] for key in PUBLIC_FIELDS}


def public_performance(db, item_id):
    rows = db.execute(
        """SELECT p.item_id,p.snapshot,p.fetched_at,i.content_type,i.published_at,
        (SELECT count(*) FROM meta_ad_assets WHERE ad_item_id=i.id) AS asset_count
        FROM meta_library_performance p JOIN meta_library_items i ON i.id=p.item_id
        WHERE p.item_id=%s OR p.item_id IN (SELECT ad_item_id FROM meta_ad_assets WHERE video_item_id=%s)
        ORDER BY p.item_id""",
        (item_id, item_id),
    ).fetchall()
    for row in rows:
        count = row.pop("asset_count")
        row["attribution"] = (
            "shared_ad"
            if count > 1
            else ("ad" if row["content_type"] == "ad" else "organic")
        )
    return rows


def new_batch(db, connection_id, kind, items):
    run = db.execute(
        "INSERT INTO meta_sync_runs(connection_id,kind,discovery_finalized) VALUES (%s,%s,true) RETURNING id",
        (connection_id, kind),
    ).fetchone()["id"]
    for item in items:
        if kind == "analysis":
            targets = [item]
            if item["content_type"] == "ad":
                targets = db.execute(
                    "SELECT i.* FROM meta_library_items i JOIN meta_ad_assets a ON a.video_item_id=i.id WHERE a.ad_item_id=%s",
                    (item["id"],),
                ).fetchall()
            if not targets:
                add_job(db, run, connection_id, kind, item["id"], item_id=item["id"])
                db.execute(
                    "UPDATE meta_jobs SET state='unavailable',error='No accessible video creative.' WHERE run_id=%s AND item_id=%s",
                    (run, item["id"]),
                )
            for target in targets:
                state = queue_analysis(db, run, target, explicit=True)
                if state == "reused":
                    add_job(
                        db, run, connection_id, kind, target["id"], item_id=target["id"]
                    )
                    db.execute(
                        "UPDATE meta_jobs SET state='reused' WHERE run_id=%s AND item_id=%s",
                        (run, target["id"]),
                    )
                elif not db.execute(
                    "SELECT 1 FROM meta_jobs WHERE run_id=%s AND item_id=%s",
                    (run, target["id"]),
                ).fetchone():
                    # Follow existing work without claiming a second processing job.
                    add_job(
                        db,
                        run,
                        connection_id,
                        kind,
                        "follow:" + str(target["id"]),
                        {"follow_item": str(target["id"])},
                    )
        else:
            if not add_job(
                db, run, connection_id, kind, item["id"], {"manual": True}, item["id"]
            ):
                add_job(
                    db,
                    run,
                    connection_id,
                    kind,
                    "follow:" + str(item["id"]),
                    {"follow_item": str(item["id"])},
                )
    finalize_runs(db)
    return run
