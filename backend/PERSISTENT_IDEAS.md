# V3 persistent ideas, feedback and publications (migrations 008–009)

One successful company-scoped generation creates one draft with editable
`title`, `concept`, and `script`. Updates replace those fields in place. Migration
009 adds current lifecycle/feedback and manual publication associations. There is
no revision history, frontend workflow, automatic matching or publishing to Meta.
Existing V1/V2 unscoped recommendation endpoints retain their current behavior.

## Integrated ownership and profiles

Apply real migrations **001–010** in order; test fixtures are never migrations.
The default `OwnershipIdeaAccess` adapter binds ideas to the existing persisted
Meta session, 006 company ownership repository, and 007 profile revisions. No new
authentication or membership system is introduced. An explicit
`app.state.idea_company_access` override remains available for contract tests;
setting it to `None` fails closed with 503.

- Live session and connection rows are locked through commit. The connection lock
  conflicts with 006 ownership changes, company archival and disconnect. Company
  authorization alone is enough for history, edits, frozen evidence and replay.
- Sources use 006's `accessible_items`; performance uses its stricter
  `direct_items` boundary through `ownership.performance`. Sharing an Ads account
  or creative never grants another company's ads or organic publication metrics.
- Generation uses the unsuppressed shared 007 profile document, if available.
  `profile_revision_id` records that shared revision; the frozen profile payload's
  `revision_ids` records both it and the exact platform dependency revisions used
  to build it. These are internal UUIDs, not provider identities. No live profile
  read is needed to reproduce saved evidence. A missing or suppressed profile is
  omitted rather than replaced with another company's profile.
- After the model call, authorization is rechecked for every source and metric
  owner. Metric owners must still be directly owned. When a profile was supplied,
  the company profile lock fences suppression/publication through persistence;
  a suppressed or replaced shared revision returns 409. This also catches removal
  of profile evidence outside the selected videos. Retry after refreshing inputs.
  Analysis/metric refresh alone can retain captured evidence; publication of a new
  shared profile during a profiled generation requires retry.

## API

All routes are below `/api/meta/companies/{company_id}`, within the existing Meta
session cookie path. Runtime `X-OpenAI-API-Key` remains request-only.

| Method/path | Behavior |
| --- | --- |
| `POST /recommendations` | Generate and return one persisted idea, or return its idempotent replay (200) |
| `GET /ideas?limit=25&after={idea_uuid}` | Company history; newest first; maximum 100; opaque UUID cursor |
| `GET /ideas/{id}` | Current text, status, feedback, generation metadata, targets and publication associations |
| `GET /ideas/{id}/evidence` | Exact structured input supplied to generation |
| `PATCH /ideas/{id}` | Update one or more of title/concept/script/status; returns current idea |
| `PUT /ideas/{id}/feedback` | Replace current feedback; returns current idea |
| `PUT /ideas/{id}/publications/{library_item_id}` | Add a manual link; duplicate is idempotent; returns current idea |
| `DELETE /ideas/{id}/publications/{library_item_id}` | Remove that link only; absent link is idempotent; returns current idea |

Generation body:

```json
{
  "request_id": "5a91fa9e-cac7-44dd-8585-438fa51b6ebd",
  "video_ids": ["1a188f51-8645-47e4-82e7-10c983511dfd"],
  "generation_brief": "An approachable demonstration",
  "target_platforms": ["instagram", "facebook"],
  "history_limit": 20
}
```

Require 1–20 distinct ordered internal library item UUIDs, completed current-version
analysis, and authorization for all selected sources and metric owners. Brief is
optional (maximum 10,000 characters). Platforms are zero, one or both of
`instagram`/`facebook`; omitted or empty means unspecified. Duplicate selections,
unknown fields, null/blank edits and unsupported platforms return 422.
Title/concept/script limits are 300/10,000/30,000 characters. Lifecycle status is
exactly `draft`, `used`, `published` or `discarded`, with `draft` as the default.

`history_limit` is 0–20, default 20. Supply latest titles (up to 300 characters) and
concept excerpts (up to 2,000 characters), status, current feedback and optional
feedback reason (up to 2,000 characters), never earlier scripts. The company/time/UUID
index supports keyset pagination and bounded generation history. This is an efficient
initial duplicate-avoidance path; it does not guarantee semantic uniqueness, search
all historical ideas, or require unique titles. No text-search index is needed yet.

## Lifecycle, feedback and manual publication behavior

`PATCH /ideas/{id}` accepts, for example, `{"status":"used"}`. All transitions
between the four statuses are allowed, including returning a discarded idea to
draft. A published status does not require a link, and links do not automatically
change status. Status describes the user's current workflow, not verified Meta
publication or measured performance.

`PUT /ideas/{id}/feedback` accepts `{"feedback":"liked"}`,
`{"feedback":"disliked","reason":"Too repetitive"}`, or `{"feedback":"none"}`.
Dislike reasons are optional; omitted, null, empty and whitespace-only reasons
normalize to null. Reasons are trimmed and limited to 2,000 characters. A nonblank
reason with `liked` or `none` is rejected with 422. Each request replaces current
feedback and clears any previous reason when none is supplied. There are no
feedback revision/event records. Unknown values, fields and null status/feedback
are rejected with 422.

Manual links accept internal library UUIDs only. The user is asserting that the
selected discovered Meta post/reel/ad corresponds to the idea; this operation does
not verify publication at Meta or infer publication from a possibly absent library
timestamp. It supports multiple items per idea and multiple ideas per item.
Existing links remain after organic account unlink, ad reassignment, or disconnect;
company identity is derived from the idea's immutable `company_id` and never moves
with current item ownership. Repeating PUT still requires current item access;
DELETE only needs current company/idea access, so obsolete links can be removed.

Idea detail/replay/mutation responses include `publications`, containing only
`library_item_id` and association `created_at`. These are historical associations,
not an access grant: no live label, URL, raw provider identity, metrics or analysis
is joined into publication output. Any future live projection must independently
use 006 ownership readers. The ordinary company history list includes status and
feedback but does not expand publication arrays. Existing frozen generation
evidence remains a separate, immutable historical record.

All operations require the persisted Meta session and company+idea UUID scope.
Link creation also authorizes the target through the default real 006 adapter,
holding session/connection locks through insertion. A shared creative never grants
access to sibling ads. Foreign/inaccessible/archived company resources return 404;
missing/expired/disconnected sessions return 401. Archived companies retain all
records and cannot change lifecycle, feedback, or links. Existing V3 reads also
remain unavailable while archived; restoring the company resumes normal access.

Generation uses at most `history_limit` (0–20) recent company ideas ordered by
creation time and UUID, via the existing `ideas_company_history` index. Feedback
on older ideas outside that window does not enter the prompt. Exact feedback and
status excerpts supplied to each generation are frozen in `prior_idea_evidence`;
later feedback edits cannot rewrite them. A small prompt instruction treats
feedback as a weaker preference signal than actual measured performance. Manual
publication links are not added as performance evidence. The model and V2
recommendation endpoints are unchanged.

## Migration 009 schema

- Existing `ideas.status TEXT NOT NULL DEFAULT 'draft'` has its draft-only CHECK
  replaced with the four-value CHECK. No duplicate lifecycle table is introduced.
- `ideas.feedback TEXT NOT NULL DEFAULT 'none'`, CHECK in none/liked/disliked.
- `ideas.feedback_reason TEXT NULL`, maximum 2,000 characters; must be null unless
  feedback is disliked. Existing ideas receive none/null without changing evidence.
- `guard_idea_update()` adds only status/feedback/feedback_reason to its mutable
  allowlist. Immutable identity, evidence and sealing protection remain intact.
- `idea_publications(idea_id UUID NOT NULL, library_item_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now())`; composite primary key
  `(idea_id, library_item_id)` prevents duplicate links. Foreign keys reference
  `ideas(id)` and `meta_library_items(id)`, both `ON DELETE RESTRICT`. Deleting a
  link deletes neither entity. Deleting a referenced entity requires explicitly
  removing its associations first, preventing accidental loss of link history.
- An index on `idea_publications(library_item_id)` supports reverse FK checks.
  The primary key serves per-idea association reads; the existing company history
  index serves bounded feedback context. No new company fields on shared content.

The final release audit required migration 010 to enforce the same-profile FK
between profile refresh requests and jobs. It does not change idea/publication
schema or add speculative query indexes. Ad discovery also now invalidates and
suppresses profiles transactionally when a creative relationship changes, closing
a stale-profile authorization gap. See [the release audit](V3_RELEASE_AUDIT.md).

## Storage and transactions

- `ideas`: owning company, current text, brief, lifecycle/feedback, request identity/hash,
  model, recommendation/evidence versions, capture/create/update timestamps,
  frozen profile revision/payload and bounded prior-idea excerpts.
- `idea_sources`: ordered source UUIDs, analysis versions, exact supplied content
  payloads and publication context. No live source FK: deletion or reassignment
  must not remove or change historical evidence.
- `idea_performance_evidence`: one supplied snapshot per metric-owning internal
  UUID per idea, fetched time, attribution and publication context.
- `idea_source_performance`: same-idea composite FKs preserve each source's metric
  mappings, including shared ads. Shared snapshots are not copied per creative.
- `idea_target_platforms`: zero or more constrained relational rows.
- `idea_generation_requests`: company/request primary key, immutable-in-service
  SHA-256 input identity, renewable claim and five-minute recovery lease. This
  small ledger may survive a failed attempt; no half-written idea/evidence survives.

The hash covers normalized client inputs, including source order, brief, platform
set and history limit. It excludes credentials and changing server defaults or
source state, so retries remain stable after refreshes/deploys. Reusing a request
UUID with different inputs returns 409, even after a failed attempt. An active
attempt also returns 409; retry later with the same request/body. A successful
replay returns the existing idea's **current edited fields** without calling OpenAI.

1. Authorize company write access and reserve the request in a short transaction.
2. Use one `REPEATABLE READ` transaction for authorization, source/version checks,
   all analysis child records, performance snapshots, profile and history. Freeze
   an allowlisted input in memory. Reject inputs exceeding 1 MiB rather than silently
   omitting source evidence. No provider response dictionaries/identity fields are
   copied; metric fields are allowlisted before both model input and persistence.
3. Close the transaction and connection, then call OpenAI with structured
   `GeneratedIdea` output and `store=False`. Refusal, truncation, invalid output,
   and provider failures save no idea.
4. Revalidate live session/company authorization for all sources and metric owners,
   holding 006's revocation-conflicting locks. Check the attempt claim and save the
   idea, all evidence, mappings and platforms in one transaction. A superseded
   attempt cannot commit. Analysis/metric refresh alone does not invalidate captured
   evidence; authorization loss does.

Database triggers prohibit evidence changes/deletion and later additions once
sealed. Generation metadata cannot change when editing. A deferred constraint
requires a sealed idea with 1–20 contiguous sources and mapped metric evidence
before commit. Evidence privileges assume a normal application role, not a DB
administrator capable of disabling triggers or truncating tables.

Model comes from `OPENAI_MODEL` (existing default `gpt-6-sol`). Recommendation
version is 4 and evidence schema version is 3; increment the appropriate constant
when changing prompt semantics or captured-input shape. Structured output follows
[OpenAI's documented Pydantic Responses parsing](https://developers.openai.com/api/docs/guides/structured-outputs).

## Verification and limitations

From `backend/`, with a disposable PostgreSQL database:

```sh
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55440/postgres \
  .venv/bin/python -m unittest discover -s tests -p 'test_persistent_ideas.py' -v
```

`test_idea_integration.py` applies the actual migration sequence through 010, including
an upgrade from populated V2 data. It runs the 007 worker with a stubbed generator
and calls the idea HTTP API using real persisted sessions and 006 ownership.
Coverage includes cross-company shared creatives, organic metric isolation,
profile/dependency revision capture, archive/session/source/profile revocation,
locks at persistence, idempotent replay and frozen evidence after profile refresh.
`test_persistent_ideas.py` additionally uses explicit test-only 006/007 stand-ins
to exercise the adapter contract, immutable storage, retries and failures.
Existing V2 database fixtures deliberately apply only 001–005.

`test_idea_feedback_publications.py` exercises 009 using actual 006 ownership and
007/008 repositories. Its upgrade test seeds an existing sealed 008 idea before
applying 009 and verifies every pre-existing field and source row is preserved.
Run it with the same command above, replacing the test filename.

Verified locally on 2026-09-26: all 25 focused 009 PostgreSQL tests passed. The full
backend suite with `TEST_DATABASE_URL` enabled ran 258 tests: 255 passed and three
optional local OCR/Whisper media tests were skipped (`RUN_MEDIA_INTEGRATION=0`).
The V2 recommendation tests passed. Python compilation and `git diff --check`
passed; no Python lint command is configured.

OpenAI output is mocked. No paid generation, production database, live Meta refresh,
or V3 workflow UX verification is claimed. The final release audit separately
verifies the existing V2 browser flow on the integrated schema. A process failure after the model call but
before commit may require another paid call after lease recovery; persistence
remains at most one idea per company/request. The bounded recent-history prompt
is duplicate avoidance, not a semantic deduplication guarantee.
