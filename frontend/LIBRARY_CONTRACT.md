# Meta library frontend contract — proposed, not implemented

The frontend implements this boundary with typed requests and runtime response
validation in `src/metaLibrary.ts`. At the start of this task the backend provided authentication, discovery, upload,
per-video metrics/analysis, and single-video recommendation routes only. Backend
library work appeared concurrently in the shared checkout. **That implementation
has a different contract and is not integrated with this frontend.** Alignment,
media import, persistence, and live acceptance remain separate work; this frontend
task makes no backend changes or migrations.

The concurrently observed routes are `GET /api/meta/library` (a different item
shape, without scope summaries), `POST /api/meta/sync` (returns a job reference),
and `POST /api/meta/recommendations` (`video_ids`, at most 20, returns model text).
The frontend below expects scoped readiness snapshots and structured concept/
script results, and covers batches of 250. Do not claim compatibility or silently
truncate selections to bridge that mismatch. These observations are a snapshot
of concurrent work, not a validation of its final implementation.

## Existing integration

Keep the existing popup login at `/api/meta/connect`, callback, and
`GET /api/meta/test`. Use existing discovery routes for Pages, linked Instagram
accounts, and ad accounts. Exhaust account pagination before auto-selection.
Accounts are named checkboxes grouped as Facebook Pages, Instagram accounts,
and Ad accounts. A sole source in a group is selected automatically; groups
with multiple sources require a choice. A Facebook source includes both Reels
and regular videos; Instagram includes supported Reels; advertising includes
video ads only. No customer chooses a media URL or enters an identifier.

All library calls use the same-origin session cookie, `cache: no-store`, and
paths under `/api/meta`, matching the existing cookie scope. No frontend key,
access token, or custom authorization header is required. No production mock
or upload fallback is installed. A 404/501 shows an unavailable-service message,
not an empty library.

## Shared types

```ts
type SourceRef = {
  platform: "facebook" | "instagram" | "meta_ads";
  account_id: string;
  page_id?: string; // present for Facebook and Page-linked Instagram
};
type Status = "new" | "analyzing" | "ready" | "unavailable" | "failed";
type LibraryItem = {
  id: string; // stable opaque library reference, never displayed
  source: SourceRef;
  title: string; // caption/title; an empty value gets a friendly fallback
  platform: SourceRef["platform"];
  content_type: "instagram_reel" | "facebook_reel" | "facebook_video" | "meta_video_ad";
  distribution: "organic" | "paid";
  status: Status; // readiness, NOT ad delivery status
  thumbnail_url: string | null; // HTTPS preview, optional
  published_at: string | null; // ISO timestamp, optional
  metrics: {
    views: number | null;
    likes: number | null;
    comments: number | null;
    shares: number | null;
  } | null;
};
```

Account identifiers are internal values obtained from discovery. The service
must authorize every requested source/item against the connected session;
client-provided references do not establish access. Item references must be
unique across sources and stable across syncs. Deduplicate overlapping Facebook
Reel/video discovery results within the organic library, while keeping paid and
organic entries distinct when their performance context differs. Metrics are
available counts, not inferred zeroes. The frontend does not rank paid and
organic content by raw counts or display model context.

## `GET /api/meta/library`

Query parameters: `sources`, a JSON-encoded `SourceRef[]`, and optional `after`,
an opaque page cursor. No names or credentials are sent in source references.

```ts
type LibraryResponse = {
  items: LibraryItem[];
  next_cursor: string | null;
  sync_state: "idle" | "syncing";
  summary: { total: number; ready: number; new: number; analyzing: number;
             unavailable: number; failed: number };
  source_errors: { source: SourceRef; code: string }[];
};
```

Counts describe the complete selected source scope, not just the current page.
Return an empty items list with total zero for an empty video library. A nonzero
total with no usable/listed videos produces the no-suitable-content state. Do
not represent non-video ads/posts as Ready video items. Summary counts and
source errors must describe the same scope on every page.

Read saved content immediately. New processing must not hide previously ready
content, and source-level sync failure must not delete saved successful items.
Readiness comes from the server; discovery's ad `status` and `selectable` flags
are not sufficient. Once ready, an item remains reusable without uploading or
reprocessing it for each generation. Never include media-fetch URLs or tokens
in error text or fields beyond the intended safe thumbnail.

The frontend reads saved content before triggering sync, polls every five
seconds while sync or New/Analyzing counts are active, and re-reads all loaded
pages to update visible statuses. It keeps selections by stable item reference.
A failed refresh preserves the previous successful view and offers retry.
Obsolete requests are aborted on scope changes and disconnects.

## `POST /api/meta/library/sync`

Request: `{ "sources": SourceRef[] }`. Response: `{ "accepted": true }`.

An acknowledgement means sync was accepted, not that processing is finished.
Progress and failures appear through library reads. The server must coalesce
repeat requests for an active source sync and reuse saved analysis for existing
content. The frontend debounces initial source changes by 300 ms, syncs after
account selection/reconnection, and also offers **Sync content**. No server-side
worker architecture or analysis algorithm is prescribed by this frontend task.

## `POST /api/meta/library/recommendations`

Request: `{ "item_ids": string[] }`, containing unique selected Ready library
references. Send one request for the entire ready subset, never one per video.
Selection spans loaded pages and has no arbitrary frontend count cap (browser
coverage includes 250 items). A future server must support practical batches
or explicitly return an actionable limit; model context sizing is server-owned.

```ts
type RecommendationResponse = {
  concept: string; // nonempty plain text
  script: string; // nonempty plain text, preserving line breaks
  used_item_ids: string[]; // at least one, subset of requested references
  skipped_items: { id: string; code: string }[];
};
```

Used and skipped references must be unique, disjoint, and together account for
all requested items. Return one idea built from all usable selected content.
Resolve saved analysis on the server and reuse the existing recommendation
logic. Server configuration provides the model credentials. If some requested
items become unavailable, return a successful idea with explicit skipped items;
if none remain usable, return an error. This structured result is a future
contract, not the current single-video `{model, response}` endpoint.

The frontend renders text safely with no HTML interpretation. It displays only
the concept, script, used count, and a friendly skipped count. Failed or malformed
responses never clear a previously successful result. Selection controls and
source changes are disabled during generation. A 90-second request timeout
allows the server's existing provider timeout to finish; other requests time out
after 20 seconds. Client abort does not imply server-side work was cancelled.

## Errors and acceptance boundary

- 401: reconnect; keep existing displayed content/results, disable generation,
  rediscover authorized accounts and revalidate the library after login.
- 403: explain missing shared access and offer reconnection through the account
  panel. Source-level `permission_missing` names the affected account.
- 404/501: library/generation is not available yet.
- 429: wait briefly and retry. Other errors/network failures: friendly retry copy.
- Do not display arbitrary backend `detail`, source error codes, internal IDs,
  provider names, stack traces, or model context to the customer.

Browser tests mock both existing and proposed endpoints. They cover connection,
accounts, pagination, readiness, batching, results, failures, and responsive
layouts. These tests do not establish actual OAuth permissions, automatic media
retrieval, saved analysis/database round trips, or provider generation. Full
frontend → API → database/analysis → UI verification remains blocked until the
future contract has a backend implementation and authorized live accounts.
