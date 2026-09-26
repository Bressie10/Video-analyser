"""Internal-UUID-only APIs for the authenticated Meta library."""

import json
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from app import meta
from app import meta_library_repository as repo
from app.meta_routes import _private
from app.recommendations import MissingAPIKeyError, recommend_videos
from app.video_repository import get_analysis

router = APIRouter(prefix="/api/meta")


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] = Field(min_length=1, max_length=100)


class RecommendationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_ids: list[UUID] = Field(min_length=1, max_length=20)


def respond(request, operation, status=200):
    try:
        repo.cipher()
        connection = repo.session_connection(request.cookies.get(meta.SESSION_COOKIE))
        result = operation(connection["id"])
        response = JSONResponse(jsonable_encoder(result), status_code=status)
    except meta.MetaNotConnected:
        response = JSONResponse(
            {"detail": "Reconnect Meta to continue."}, status_code=401
        )
    except meta.MetaConfigurationError:
        response = JSONResponse(
            {"detail": "Persistent Meta library is not configured."}, status_code=503
        )
    except (psycopg.Error, ValueError):
        response = JSONResponse(
            {"detail": "Library storage is unavailable."}, status_code=503
        )
    except HTTPException as error:
        response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
    return _private(response)


def selected(db, connection_id, ids):
    unique = list(dict.fromkeys(ids))
    rows = db.execute(
        "SELECT * FROM meta_library_items WHERE connection_id=%s AND id=ANY(%s)",
        (connection_id, unique),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [str(i) for i in unique if i not in by_id]
    if missing:
        raise HTTPException(
            404, {"message": "Library items were not found.", "item_ids": missing}
        )
    return [by_id[i] for i in unique]


def ad_assets(db, item):
    assets = [
        repo.public_item(r)
        for r in db.execute(
            "SELECT i.* FROM meta_library_items i JOIN meta_ad_assets a ON a.video_item_id=i.id WHERE a.ad_item_id=%s ORDER BY i.id",
            (item["id"],),
        ).fetchall()
    ]
    item["assets"] = assets
    if assets:
        states = {asset["analysis_state"] for asset in assets}
        item["analysis_state"] = next(
            (
                state
                for state in (
                    "processing",
                    "queued",
                    "failed",
                    "unavailable",
                    "unsupported",
                    "deferred",
                    "discovered",
                )
                if state in states
            ),
            "completed",
        )
        item["analysis_error"] = next(
            (a["analysis_error"] for a in assets if a["analysis_error"]), None
        )
    return item


@router.get("/library")
def library(
    request: Request, limit: int = Query(25, ge=1, le=100), after: UUID | None = None
):
    def operation(connection_id):
        with repo.database() as db:
            rows = db.execute(
                """SELECT i.*,a.label AS account_label FROM meta_library_items i
                JOIN meta_accounts a ON a.id=i.account_id WHERE i.connection_id=%s
                AND (%s::uuid IS NULL OR i.id>%s) ORDER BY i.id LIMIT %s""",
                (connection_id, after, after, limit + 1),
            ).fetchall()
            items = []
            for row in rows[:limit]:
                item = {
                    **repo.public_item(row),
                    "account_label": row["account_label"],
                    "performance": repo.public_performance(db, row["id"]),
                }
                if row["content_type"] == "ad":
                    ad_assets(db, item)
                items.append(item)
            return {
                "items": items,
                "next_cursor": str(rows[limit - 1]["id"])
                if len(rows) > limit
                else None,
            }

    return respond(request, operation)


@router.get("/library/{item_id}")
def detail(request: Request, item_id: UUID):
    def operation(connection_id):
        with repo.database() as db:
            item = selected(db, connection_id, [item_id])[0]
            result = {
                **repo.public_item(item),
                "performance": repo.public_performance(db, item_id),
            }
            if item["content_type"] == "ad":
                ad_assets(db, result)
        result["analysis"] = (
            get_analysis(item["video_id"], connection_id=connection_id)
            if item["video_id"]
            else None
        )
        return result

    return respond(request, operation)


@router.post("/sync", status_code=202)
def sync(request: Request):
    def operation(connection_id):
        with repo.database() as db:
            return {"job_id": repo.enqueue_sync(db, connection_id)}

    return respond(request, operation, 202)


@router.get("/jobs/{job_id}")
def job_status(
    request: Request,
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    after: UUID | None = None,
):
    def operation(connection_id):
        with repo.database() as db:
            run = db.execute(
                "SELECT id,kind,created_at,finished_at FROM meta_sync_runs WHERE id=%s AND connection_id=%s",
                (job_id, connection_id),
            ).fetchone()
            if not run:
                raise HTTPException(404, "Job was not found.")
            counts = {
                r["state"]: r["count"]
                for r in db.execute(
                    "SELECT state,count(*) AS count FROM meta_jobs WHERE run_id=%s GROUP BY state",
                    (job_id,),
                ).fetchall()
            }
            rows = db.execute(
                """SELECT id,COALESCE(item_id,(payload->>'follow_item')::uuid) AS item_id,kind,state,attempts,error
                FROM meta_jobs WHERE run_id=%s AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s""",
                (job_id, after, after, limit + 1),
            ).fetchall()
            failures = sum(
                counts.get(s, 0)
                for s in ("failed", "unavailable", "unsupported", "cancelled")
            )
            state = (
                ("partial_failure" if failures else "completed")
                if run["finished_at"]
                else ("blocked" if counts.get("blocked") else "running")
            )
            return {
                **run,
                "state": state,
                "counts": counts,
                "items": rows[:limit],
                "next_cursor": str(rows[limit - 1]["id"])
                if len(rows) > limit
                else None,
            }

    return respond(request, operation)


def batch(request, body, kind):
    def operation(connection_id):
        with repo.database() as db:
            items = selected(db, connection_id, body.item_ids)
            return {"job_id": repo.new_batch(db, connection_id, kind, items)}

    return respond(request, operation, 202)


@router.post("/library/analyze", status_code=202)
def analyze(request: Request, body: Selection):
    return batch(request, body, "analysis")


@router.post("/library/metrics/refresh", status_code=202)
def refresh(request: Request, body: Selection):
    return batch(request, body, "metrics")


def recommendation_evidence(connection_id, ids):
    with repo.database() as db:
        items = selected(db, connection_id, ids)
        incomplete = [
            str(i["id"])
            for i in items
            if not i["video_id"] or i["analysis_version"] != repo.ANALYSIS_VERSION
        ]
        if incomplete:
            raise HTTPException(
                409,
                {
                    "message": "Select videos with completed current-version analysis.",
                    "video_ids": incomplete,
                },
            )
        videos, performances = [], {}
        for item in items:
            analysis = get_analysis(item["video_id"], connection_id=connection_id)
            if analysis is None:
                raise HTTPException(
                    409,
                    {
                        "message": "Stored analysis is incomplete.",
                        "video_ids": [str(item["id"])],
                    },
                )
            snapshots = repo.public_performance(db, item["id"])
            for snapshot in snapshots:
                performances[str(snapshot["item_id"])] = snapshot
            videos.append(
                {
                    **analysis,
                    "analysis_version": item["analysis_version"],
                    "published_at": item["published_at"],
                    "platform": item["platform"],
                    "performance_ids": [str(s["item_id"]) for s in snapshots],
                }
            )
    evidence = jsonable_encoder(
        {"videos": videos, "performance_snapshots": list(performances.values())}
    )
    if len(json.dumps(evidence).encode()) > 1024 * 1024:
        raise HTTPException(
            413, "Selected evidence exceeds 1 MiB. Select fewer videos."
        )
    return evidence


@router.post("/recommendations")
def recommendations(
    request: Request,
    body: RecommendationSelection,
    runtime_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
):
    def operation(connection_id):
        evidence = recommendation_evidence(connection_id, body.video_ids)
        try:
            return recommend_videos(evidence, api_key=runtime_api_key)
        except MissingAPIKeyError:
            raise HTTPException(503, "OpenAI API key is not configured.") from None
        except OpenAIError:
            raise HTTPException(502, "OpenAI request failed.") from None

    return respond(request, operation)


@router.post("/disconnect")
def disconnect(request: Request):
    response = respond(
        request,
        lambda connection_id: repo.disconnect(connection_id) or {"connected": False},
    )
    if response.status_code == 200:
        response.delete_cookie(
            meta.SESSION_COOKIE,
            path="/api/meta",
            secure=True,
            httponly=True,
            samesite="lax",
        )
    return response
