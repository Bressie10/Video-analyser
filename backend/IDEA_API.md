# V4 Wave 2 idea workflow API

All routes below use `/api/meta/companies/{company_id}` and the existing authenticated
Meta session cookie. Company, source, idea and publication IDs are internal UUIDs.
No provider IDs, tokens, raw provider responses or live metrics are returned by the
new history/picker projections. Responses are private and non-cacheable.

## Generate one saved idea

`POST /recommendations`

```json
{
  "request_id": "UUID idempotency key",
  "video_ids": ["explicit library item UUID"],
  "generation_brief": "Optional brief",
  "target_platforms": ["instagram", "facebook"]
}
```

- `request_id`: required UUID, scoped to company. Keep the same payload and key on
  retry; reuse with changed inputs returns 409. Target ordering is canonicalized.
- `video_ids`: required 1–20 unique **library item UUIDs**, not analysis/video UUIDs.
  Each must be currently accessible to that company with completed current-version
  analysis. No source selection happens server-side.
- `generation_brief`: optional/null, maximum 10,000 characters.
- `target_platforms`: required 1–2 unique values: `instagram`, `facebook`.
  Missing/empty selections and `meta_ads` return 422. The UI defaults to all linked
  publishing platforms and sends its explicit selection. Targets do not themselves
  create links or authorize publishing; V3 does not require a target account link.
- Existing `history_limit` remains optional (default 20, range 0–20) for bounded
  prior-idea context. Frontend callers can omit it.
- Optional `X-OpenAI-API-Key` is request scoped; otherwise backend configuration applies.

Returns HTTP 200 with exactly one saved Idea object. Retries return that same idea,
including any later edits. There is no disposable prose-only response. V3's usable
shared profile revision and dependency provenance are captured, or omitted under
its existing missing/suppressed profile policy. Model generation runs outside DB
transactions; access and captured profile/metric ownership are checked again before
atomic persistence. Evidence remains immutable.

## Idea object

Generation, detail, edit, feedback and publication mutations return the existing
saved Idea shape (timestamps are ISO 8601 strings; nullable values are JSON null):

```text
{
  id, company_id, title, concept, script,
  status, feedback, feedback_reason,
  generation_brief, target_platforms: ["facebook", "instagram"],
  publications: [{library_item_id, created_at}],
  request_id, request_hash, recommendation_version, model,
  evidence_schema_version, evidence_captured_at, profile_revision_id,
  created_at, updated_at
}
```

## History and explicit Save

| Method | Suffix | Request / response |
| --- | --- | --- |
| GET | `/ideas` | Filtered `{items: [Summary], next_cursor: UUID or null}` |
| GET | `/ideas/{idea_id}` | Saved Idea |
| GET | `/ideas/{idea_id}/evidence` | Existing immutable evidence object |
| PATCH | `/ideas/{idea_id}` | Explicit Save: any nonempty subset of `{title, concept, script, status}`; returns Idea |
| PUT | `/ideas/{idea_id}/feedback` | `{feedback: "liked"\|"disliked"\|"none", reason?: string\|null}`; returns Idea |
| GET | `/ideas/{idea_id}/publications` | `{items: [{library_item_id, created_at}]}` |
| PUT | `/ideas/{idea_id}/publications/{library_item_id}` | No body; add association, returns Idea |
| DELETE | `/ideas/{idea_id}/publications/{library_item_id}` | No body; remove association, returns Idea |
| GET | `/publication-options` | Picker page described below |

Summary fields: `id`, `title`, `concept`, `status`, `feedback`, `feedback_reason`,
`target_platforms`, `created_at`, `updated_at`. Fetch detail for the complete script.

History query parameters (combined with AND):

| Parameter | Meaning |
| --- | --- |
| `search` | Literal case-insensitive substring across saved title/concept/script; trimmed, max 200 characters; blank means no search |
| `status` | `draft`, `used`, `published`, `discarded` |
| `feedback` | `none`, `liked`, `disliked` |
| `target_platform` | `instagram` or `facebook`; matches ideas containing that target |
| `created_from` | Inclusive creation timestamp, ISO 8601 with timezone |
| `created_to` | Exclusive creation timestamp, ISO 8601 with timezone; must exceed `created_from` |
| `limit` | Default 25, range 1–100 |
| `after` | Previous page's `next_cursor` UUID |

Company and all filters are applied in SQL before the limit. Ordering is
`created_at DESC, id DESC`; cursors must belong to the same company. Preserve filters
when requesting another page and reset the cursor when filters change. This is live
keyset pagination, not a snapshot: concurrent edits can change filter membership.
For a UI date range, send start-of-day and next-day boundaries in the intended timezone.

Save changes only mutable title/concept/script and lifecycle status. Limits are
300/10,000/30,000 characters, respectively; blank/null edits are rejected. Feedback
reason is optional, trimmed, at most 2,000 characters, and only allowed for `disliked`.
Setting `liked` or `none` clears the old reason. Neither Save nor lifecycle/feedback/
publication mutations change generation evidence. Publication links do not implicitly
change lifecycle status.

## Publication picker and associations

`GET /publication-options?limit=25&after=UUID` returns:

```text
{
  items: [{id, platform, content_type, label, published_at}],
  next_cursor: UUID or null
}
```

Candidates are currently **directly owned**, dated Instagram/Facebook organic posts,
ordered by `published_at DESC, id DESC`. Company scope is applied before pagination.
No completed-analysis requirement applies. Undated content, ads and shared creatives
are excluded from this picker; existing V3 publication-add ownership rules remain
unchanged. Legacy labels containing provider IDs/URLs use a neutral display fallback. Limits are 1–100, default 25; inaccessible/noncandidate
cursors return 404. Candidates are local library records, not a live Meta fetch.

Associations are manual, allow multiple posts, and add/remove are idempotent. They
neither publish to Meta nor prove causation. Historical association UUIDs and link
dates survive loss of source access, but never grant access to live metadata/metrics.
Adding requires current company/item access. Removal only needs access to the idea's
active company, so an inaccessible historical link can still be removed.

## Authorization, errors and integration

V3 rules remain: archived companies deny generation, all mutations **and idea reads**
with 404; restore restores access. Foreign/sibling resources and cursors fail closed
with 404. Missing/expired/disconnected sessions return 401. Validation returns 422;
changed idempotency payloads, in-progress claims or changed evidence return 409.
Evidence over 1 MiB returns 413; invalid model output returns 502; unavailable storage
or missing model configuration returns 503. Error bodies use `detail`; FastAPI
validation errors use a list of validation details.

The frontend should send its active company UUID and explicit sources even for
“All analyzed content” (resolve the current 20 most recent analyzed items there).
No frontend was implemented in this change. Existing unscoped V2
`POST /api/meta/recommendations` remains unchanged. No migration is required beyond
existing migrations 001–009.

## Verification

From `backend`, with dependencies installed and a disposable UTF-8 PostgreSQL server:

```sh
TEST_DATABASE_URL='postgresql://USER@localhost:PORT/postgres' .venv/bin/python -m unittest discover -s tests
```

`test_v4_idea_api.py` exercises real migrations, ownership, sessions, profile provenance,
API requests, persistence, filters, picker and archive boundaries. Existing persistent
idea/integration/feedback tests cover evidence sealing, retries and access races.
OpenAI/Meta calls are controlled fixtures; tests do not establish live provider access.
