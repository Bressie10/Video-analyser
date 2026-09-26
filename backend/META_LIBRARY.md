# Meta library architecture and APIs

The integrated V2 frontend consumes this library. See [README](../README.md) for
local/Meta setup, [DATABASE](../DATABASE.md) for migrations and storage, and the
[frontend guide](../frontend/LIBRARY_CONTRACT.md) for selection/display behavior.

## Architecture and authorization

Discovery → PostgreSQL source identities/jobs → content analysis and metric jobs
→ saved library → multi-video recommendation evidence → OpenAI idea/script.

Content processing (`app/analysis_pipeline.py` and `app/video_processing.py`)
produces metadata, transcript segments, scene boundaries, OCR and motion events.
It makes no performance-provider requests. Expensive analysis is reused by stable
source identity and pipeline version. Performance collection runs separately and
can refresh snapshots without downloading or analyzing the video again.

The library uses `instagram`, `facebook` and `meta_ads` provider identities.
Instagram professional video media/Reels and Facebook Page videos/Reels supply
content; ads link to accessible video assets. `tiktok` remains supported only by
the legacy upload/metrics path. Discovery is limited to assets granted by Meta;
account filters in the UI do not restrict backend synchronization.

Persistent authorization requires `DATABASE_URL`, migrations 001–005 and
`META_TOKEN_ENCRYPTION_KEY`. The callback exchanges a long-lived User token,
verifies permissions/identity, encrypts the credential, stores a hashed browser
session, and returns `{"connected":true,"job_id":"INTERNAL_UUID"}`. Reconnecting
the same identity retains its library; another identity has a separate library.
The Secure, HttpOnly, SameSite=Lax cookie is scoped to `/api/meta`. OAuth states
remain process-local, single-use and expire after ten minutes; use a single local
Uvicorn process for the documented development flow.

Without the encryption key, compatibility OAuth uses in-memory sessions and has
no automatic library access. Persistent tokens still expire or can be revoked;
jobs then require reconnection. Disconnect clears credentials/sessions and cancels
pending work, retaining saved content. Provider URLs, tokens and callback query
strings must not be exposed in proxy/APM logs. New library APIs enforce connection
ownership; legacy public analysis endpoints cannot read imported Meta analyses.

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
- Selecting discovered/deferred content in the frontend requests explicit preparation,
  including historical videos outside the automatic window. Failed or incomplete
  analyses can be retried through the backend API. Replacement is atomic and retains
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

All library routes use the secure HTTP-only `meta_session` cookie at `/api/meta`.
Responses use `Cache-Control: no-store`; identifiers exposed by these routes are
internal UUIDs, not provider IDs.

| Method and path | Input / result |
| --- | --- |
| `GET /api/meta/library` | `limit=1..100` (default 25), optional UUID `after`; returns `items`, `next_cursor` |
| `GET /api/meta/library/{item_id}` | Item, stored `analysis`, `performance`, and ad `assets` where relevant |
| `POST /api/meta/sync` | No body; 202 with `job_id` |
| `GET /api/meta/jobs/{job_id}` | `limit=1..100` (default 100), UUID `after`; run state, counts, per-task results, next cursor |
| `POST /api/meta/library/analyze` | `{"item_ids":["UUID",...]}`; 1–100 selections; 202 with `job_id` |
| `POST /api/meta/library/metrics/refresh` | Same selection body; refresh without analysis; 202 with `job_id` |
| `POST /api/meta/recommendations` | `{"video_ids":["UUID",...]}`; 1–20 analyzed video UUIDs |
| `POST /api/meta/disconnect` | Removes credentials/sessions and cancels work; retains stored library |

Video `id` and `video_id` are the same after successful analysis; before analysis
`video_id` is null. An ad has its own `id`; select its assets' `video_id` values for
recommendations. Selecting an ad for an analysis batch expands its video assets.
Body limits are validated before repeated selection values are deduplicated.
Unknown/inaccessible selections return 404; incomplete or outdated recommendation selections return 409 with internal IDs.

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

The legacy `/api/videos/{video_id}/analysis` and single-video recommendation
routes remain available for uploads but cannot read private imported Meta analyses. Use the
authenticated library routes for Meta items. Legacy upload snapshots have no
external identity and cannot be safely matched to newly discovered content.

## Runtime operations

The FastAPI lifespan starts one analysis slot and two provider I/O slots when the
database and encryption key are configured. PostgreSQL advisory locks coordinate
slots across processes. `META_WORKER_ENABLED=false` disables this work; no Redis,
Celery or cron service is required. Daily sync needs the backend running; it is
not a push notification/webhook subscription.

Jobs, claims, leases, errors and cursors persist. Heartbeats renew two-minute
leases every 20 seconds. Transient failures get up to three total attempts with
exponential delay; authorization failures block until reconnection. Poll job
progress and inspect safe worker warnings to diagnose stalls. Active analysis
can outlast shutdown waiting; expired leases allow interrupted work to recover.

## Other and compatibility APIs

These routes remain implemented but are not the normal V2 customer workflow.
Meta discovery and per-video metric routers are marked deprecated in OpenAPI.
All IDs below are placeholders; provider IDs come from authorized discovery,
not arbitrary public URLs. The full request schemas are available in `/docs`.

| Method and route | Input / behavior |
| --- | --- |
| `GET /health` | API liveness |
| `GET /health/db` | `SELECT 1`; 503 if database configuration/connection is unavailable |
| `GET /api/meta/connect` | Starts OAuth redirect |
| `GET /api/meta/callback` | OAuth `state`, `code` or error query; saves session and queues V2 sync |
| `GET /api/meta/test` | Status probe: 200 `{connected:false}` when absent/expired/revoked, 200 `{connected:true}` when valid; real permission/provider failures remain errors, not asset-access proof |
| `POST /api/photos` | Multipart `photo`; accepts image MIME type and acknowledges receipt only; no analysis/storage |
| `POST /api/videos` | Multipart `video`, optional `tiktok_url`; processes upload and returns analysis plus `video_id` when database configured |
| `GET /api/videos/{video_id}/analysis` | Saved legacy upload analysis |
| `POST /api/videos/{video_id}/recommendations` | One legacy upload analysis; optional `X-OpenAI-API-Key`; returns `{model,response}` |
| `GET /api/tiktok/connect` | Starts TikTok OAuth |
| `GET /api/tiktok/callback` | OAuth code/state exchange |
| `GET /api/tiktok/videos` | One page of authorized public videos/counts; optional nonnegative `cursor` |
| `GET /api/meta/discovery/pages` | Accessible Pages |
| `GET /api/meta/discovery/pages/{page_id}/instagram-accounts` | Linked professional Instagram account |
| `GET /api/meta/discovery/pages/{page_id}/facebook/{kind}` | `kind` is `reels` or `videos` |
| `GET /api/meta/discovery/pages/{page_id}/instagram/{account_id}/media` | Instagram media |
| `GET /api/meta/discovery/ad-accounts` | Accessible ad accounts |
| `GET /api/meta/discovery/ad-accounts/{account_id}/ads` | Ads |
| `POST /api/meta/instagram/reels/{instagram_media_id}/metrics` | JSON `{video_id}`; attach Reel snapshot to a legacy upload |
| `POST /api/meta/facebook/{media_kind}/{facebook_video_id}/metrics` | JSON `{video_id,page_id}`; `media_kind` is `videos` or `reels` |
| `POST /api/meta/ads/{ad_id}/metrics` | JSON `{video_id,since,until}`; ISO reporting dates |

Legacy discovery lists return `{items,next_cursor}` with optional `after` except
for the linked Instagram-account lookup. They expose provider selection IDs but
not tokens; the V2 library uses internal IDs instead. Manual metric attachments
trust the caller to match an upload to provider content, store one latest snapshot,
and reject another source with 409. They do not provide automatic deduplication.
Missing videos return 404; unsupported/unavailable metrics generally return 422,
authentication 401, denied access where classified 403, provider failures 502 and
storage failures 503. Failures preserve previous snapshots.

Legacy uploads accept MP4/MOV/MKV/WebM, capped at 500 MiB and ten minutes. Video is
normalized to MP4/H.264/AAC (maximum 1,920 pixels per dimension), with 16 kHz mono
WAV transcription. Silent media is supported by automatic Meta imports; legacy
upload validation still requires audio. Neither flow retains processed files.

TikTok needs its three environment variables, an HTTPS `/api/tiktok/callback`
registered with Login Kit, and Display API `video.list` access. Tokens stay in
process memory and refresh when needed; restart or another worker requires
reconnection. Optional upload `tiktok_url` must be a canonical full HTTPS video
URL owned by the authorized account. The file is not content-matched to that URL;
TikTok IDs/URLs are not persisted. The session cookie is scoped to `/api`.

Recommendation requests use the configured backend key unless a caller supplies
request-only `X-OpenAI-API-Key`. The key is not persisted. The Responses request
uses `store=False`; the API returns plain text with no enforced output schema.
The current UI uses the backend key, not a customer key field.

### Metric semantics

Common counts are `view_count`, `like_count`, `comment_count`, `share_count`, with
separate `performance_source`. Null means unknown; explicit zero remains zero.
Instagram maps `views`, `likes`, `comments`, `shares`. Facebook regular videos map
`total_video_views`, like-only reactions and comment/share story actions; Reels
map `fb_reels_total_plays`, like reactions and comment/share social actions.
Video views and Reel plays have different definitions and may include promoted
distribution; naming a snapshot organic does not prove exclusively organic reach.
The library can additionally collect Instagram reach and regular Facebook video
impressions/reach when available. Ads retain reporting/currency/attribution context
as described in [Meta Ads JSONB](../DATABASE.md#meta-ads-jsonb). Do not compare paid
and organic counts as equivalent exposure or sum shared ad totals across assets.

## Verification boundary

Use the commands in [README testing](../README.md#testing). Unit/API tests mock
providers; PostgreSQL tests exercise migrations, source identity, caching, metrics,
ownership, leases, failure recovery and recommendation evidence. Generated-media
checks exercise local OCR/Whisper and processing on known fixtures. Browser
integration runs real application routes/workers/database with external providers
replaced by fixtures. None establishes live Meta permissions, real media URL
availability, OpenAI account access or quality on arbitrary production footage.
