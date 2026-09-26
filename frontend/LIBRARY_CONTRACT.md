# Implemented Meta library frontend contract

The frontend uses the completed FastAPI V2 contract. `src/metaLibrary.ts`
validates wire responses and adapts them to the existing business library UI.
There are no production fixtures or manual upload/ID entry fallbacks.

## Backend integration

The authoritative [API reference](../backend/META_LIBRARY.md#api-contract) defines
library reads, sync/jobs, preparation and recommendations. `src/metaLibrary.ts`
reads all library/job pages with `limit=100`; `src/useMetaLibrary.ts` coordinates
refresh and preparation. `src/VideoLibrary.tsx` maps the saved items to selection
and generation controls. The customer action is **Generate a new video idea**.

All requests use the same-origin session cookie and disable caching. Existing
popup authentication is retained; its callback job is resumed instead of queuing
another sync. Cached content loads first. Sync and preparation jobs are polled
while running, with library refreshes every five seconds. Filters do not trigger
new syncs. All library pages are read before automatic account selection.

## Library and selection

Items use the backend's `label`, `platform`, `content_type`, `analysis_state`,
`video_id`, `analysis_version`, and performance snapshots. Additive public
`account_id` (internal UUID) and `account_platform` metadata identify named
accounts reliably, including same-name accounts and ad-owned Facebook assets.
Identifiers are only request values, never customer-facing copy.

Account filters are local and derived from stored library items. A single account
per platform is selected automatically. Accounts with no stored content cannot be
listed by this endpoint. Counts describe loaded, filtered cards, not backend task
counts or invented global totals. The backend supplies no thumbnail URLs.

Organic cards and paid ad cards remain distinct. An ad expands to its linked
assets for readiness, preparation and generation. Ad-only asset rows are hidden
behind their ad cards; shared organic assets remain visible. Only the card's own
performance snapshot is shown; missing metrics are not zero. Shared ad totals
are labelled as describing the whole ad.

Selecting discovered/deferred content queues preparation in chunks of 100.
Changing or clearing selection cancels unsent chunks; accepted jobs continue.
Queued/processing content displays Analyzing, completed content with a stored
video displays Ready, and unavailable/unsupported/failed content is disabled.
Partly ready ads can contribute their ready assets. Generation deduplicates
leaf library references (the backend currently persists video IDs equal to these references) and explicitly enforces the backend's 20-video limit;
it never silently truncates a selection. Previously completed analysis is reused.

## Results and errors

The backend returns model text, not structured concept/script or skipped-item
lists. The frontend extracts the prompted New video idea and Script sections
when present; otherwise it preserves the complete response as plain text.
Internal UUIDs are removed from displayed text; model metadata is not shown.

Successful content and ideas survive refresh, preparation and generation errors.
401/blocked jobs require reconnect; 403 explains missing access. Partial jobs
retain successful items. 409 queues affected stale content for preparation
without automatically generating again. 404 refreshes the library. 413 explains
the backend's 1 MiB evidence limit and asks for fewer videos. The backend does not
provide partial recommendation success, thumbnails or empty-account enumeration.

## Verification

See [README testing](../README.md#testing) for commands and prerequisites.
Browser fixtures cover connection, filters, pagination, preparation, deduplicated
selection, the 20-ready-video limit, errors and desktop/320px layouts.
`npm run test:integration` uses real Vite/FastAPI HTTP, persistent sessions, workers,
known-sample media analysis, PostgreSQL and recommendation evidence assembly.
External Meta/media delivery and OpenAI remain fixtures, so live authorization
and provider output require separate verification.
