# Automatic Meta library

The automatic flow is backend-only. Existing raw-Meta-ID discovery and metric
routes remain deprecated compatibility APIs. New consumers should use the
internal-UUID APIs below. No manual upload or external ID is needed.

## Setup and rollout

1. Install `backend/requirements.txt` (adds `cryptography` for credential encryption).
2. Back up the database and apply `migrations/005_meta_library.sql` after migrations
   001–004. It is additive and preserves existing videos, child records, metric
   snapshots, UUIDs, and timestamps. Existing analyses receive version 1.
3. Set `META_TOKEN_ENCRYPTION_KEY` to a Fernet key in the server environment/secret
   manager. Generate it with `python -c 'from cryptography.fernet import Fernet;
   print(Fernet.generate_key().decode())'` in a private terminal. Never commit it.
   Keep the key stable across restarts; replacing it requires reconnecting Meta.
4. Run the existing FastAPI application. Its lifespan starts one content-analysis
   slot and two provider I/O slots, coordinated by PostgreSQL advisory locks across
   processes. `META_WORKER_ENABLED=false` disables workers for maintenance/tests.
5. Connect through `/api/meta/connect`. The callback exchanges a long-lived user
   token, encrypts it, persists a hashed browser session, and returns
   `{"connected": true, "job_id": "INTERNAL_UUID"}`. Poll the job and library APIs.

Without an encryption key the old session-only OAuth flow remains available for
compatibility, but automatic library endpoints return 503. There is no plaintext
credential fallback. Automatic sync requires the key, migration, running backend,
and valid Meta authorization. Tokens are not valid indefinitely: expiration or
revocation pauses jobs until reconnection. A different Meta identity receives a
separate library. Pending OAuth states remain short-lived process memory.

## Scheduling and caching

- Sync runs immediately after connection, then daily. Explicit sync is always
  available and returns an already-active sync rather than creating a duplicate.
- Discovery reads provider pages of up to 100 records, persists progress, and
  retains older content. One account failure does not roll back other accounts.
- Initial import analyzes the newest 25 video assets from the last 90 days across
  the discovered accounts. The selection is persistent. Later syncs do not consume
  deferred history. Newly accessible accounts receive a bounded initial import.
- New publications after an account's initial discovery are analyzed automatically.
  Missing publication dates remain manual-only. Content at least 90 days old is
  not newly selected for automatic analysis or metric refresh.
- Successfully analyzed matching source IDs at `ANALYSIS_VERSION` reuse their
  analysis without downloading media. Increment the version constant in
  `app/meta_library_repository.py` when the pipeline meaningfully changes.
  Previously analyzed items can then be reprocessed regardless of age. Unselected
  historical items remain deferred. No public force-reanalysis endpoint is added.
- Failed or incomplete analyses can be retried. Replacement is atomic and retains
  the existing video UUID; failures preserve the last successful result.
- Metrics are independent jobs and remain available even when media cannot be
  downloaded. Automatic metrics use a strict rolling 90-day UTC publication cutoff;
  older snapshots remain untouched. Manual refresh bypasses this age cutoff.
- Organic snapshots retain available engagement and optional exposure fields.
  Missing fields are unknown. Ads use the existing provider from ad creation date
  through the current date in the ad account's timezone, retaining currency and
  attribution settings. Paid/organic counts and overlapping actions are not summed.
- The same Facebook video discovered through organic and ad routes shares analysis.
  Multiple ad records retain individual snapshots. Multi-asset ad evidence is
  labeled `shared_ad`, not attributed to one creative. Exact creative delivery and
  historical creative changes cannot be inferred from ad-level totals.
- Media is fetched on demand into temporary files and removed after analysis.
  Signed media URLs are neither persisted nor returned. Limits remain 500 MiB,
  10 minutes, and five minutes for download. Silent Meta videos receive empty
  transcripts and normal scene/OCR/motion analysis. Unsupported formats, unavailable
  sources, and provider permissions have explicit per-item outcomes.

## API contract

All new routes use the secure HTTP-only `meta_session` cookie at `/api/meta`.
Responses use `Cache-Control: no-store` and contain internal UUIDs only.

| Method and path | Input / result |
| --- | --- |
| `GET /api/meta/library` | `limit=1..100`, optional UUID `after`; returns `items`, `next_cursor` |
| `GET /api/meta/library/{item_id}` | Item, stored `analysis`, `performance`, and ad `assets` where relevant |
| `POST /api/meta/sync` | No body; 202 with `job_id` |
| `GET /api/meta/jobs/{job_id}` | `limit=1..100`, UUID `after`; run state, counts, per-task results, next cursor |
| `POST /api/meta/library/analyze` | `{"item_ids":["UUID",...]}`; 1–100 selections; 202 with `job_id` |
| `POST /api/meta/library/metrics/refresh` | Same selection body; refresh without analysis; 202 with `job_id` |
| `POST /api/meta/recommendations` | `{"video_ids":["UUID",...]}`; 1–20 analyzed video UUIDs |
| `POST /api/meta/disconnect` | Removes credentials/sessions and cancels work; retains stored library |

Video `id` and `video_id` are the same after successful analysis; before analysis
`video_id` is null. An ad has its own `id`; select its assets' `video_id` values for
recommendations. Selecting an ad for an analysis batch expands its video assets.
Repeated selection values are deduplicated. Unknown/inaccessible selections return
404; incomplete or outdated recommendation selections return 409 with internal IDs.

Item states: `discovered`, `deferred`, `queued`, `processing`, `completed`, `failed`,
`unavailable`, `unsupported`. `analysis_error` and `metrics_error` are safe messages.
Performance entries include snapshot provenance, `fetched_at`, and attribution.
Ads include their assets and aggregate readiness. Job results expose `completed`,
`reused`, `failed`, `unavailable`, `unsupported`, `blocked`, or `cancelled` per task.
A finished run with unsuccessful tasks reports `partial_failure`. Discovery tasks
may have no item UUID because the item is not known yet. Progress lists are paginated.

Recommendations use one evidence set containing all selected stored analyses and
deduplicated organic/ad snapshots. No processing jobs or Graph requests occur.
The current OpenAI model, optional request-only `X-OpenAI-API-Key`, and
`{"model":"...","response":"..."}` output remain unchanged. Requests over 1 MiB of
serialized evidence return 413; evidence is never silently truncated. Output asks
for observations/uncertainties, one original idea, and one usable script.

The legacy `/api/videos/{id}/analysis` and single-video recommendation routes remain
available for uploads but cannot read private imported Meta analyses. Use the
authenticated library routes for Meta items. Legacy upload snapshots have no
external identity and cannot be safely matched to newly discovered content.

## Operations and verification

Jobs, claims, leases, safe errors, and cursors persist in PostgreSQL. Heartbeats
renew two-minute leases every 20 seconds. Transient failures retry three times
with exponential delay; authorization failures wait for reconnection. Worker
health can be checked by polling job progress and examining safe worker warnings.
Deployments need a continuously running backend; no Redis, Celery, or cron service
is required. On shutdown active CPU work may finish; leases recover interrupted jobs.

Run from `backend`:

```sh
TEST_DATABASE_URL=postgresql://... .venv/bin/python -m unittest discover -s tests
```

Database tests create and remove isolated schemas. They cover populated-schema
migration, API → queue → provider → storage → library, caching, metrics, failure
recovery, privacy, and recommendations with mocked providers. Set
`RUN_MEDIA_INTEGRATION=1` for generated-sample tests using local OCR/Whisper models;
these are fixture checks, not validation on arbitrary production footage.
Live Meta access, permission-dependent source URLs, and real OpenAI output require
separate verification with an authorized account. Frontend integration is outside
this backend change.

## Implementation files

- New services: `app/meta_library_repository.py`, `app/meta_library_discovery.py`,
  `app/meta_library_metrics.py`, `app/meta_library_worker.py`,
  `app/meta_library_routes.py`, `app/meta_media.py`, and `app/analysis_pipeline.py`.
- Existing backend changes: `app/main.py`, `app/meta.py`, `app/meta_routes.py`,
  `app/instagram.py`, `app/recommendations.py`, `app/video_processing.py`, and
  `app/video_repository.py`. The discovery, Facebook, Instagram, and Ads legacy
  route modules are marked deprecated in OpenAPI.
- Schema and checks: `migrations/005_meta_library.sql`, `tests/test_meta_library.py`,
  and `tests/test_meta_media_pipeline.py`.
- Dependency/setup documentation: `requirements.txt`, this guide, root
  `.env.example`, `README.md`, and `DATABASE.md`.

The real-media round trip also exposed an existing motion-field mismatch:
the detector emits `start`/`end` while persistence expects
`start_seconds`/`end_seconds`. The shared pipeline now normalizes those fields;
both uploads and automatic imports can persist actual motion results.
