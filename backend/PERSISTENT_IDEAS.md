# V3 persistent ideas (migration 008)

One successful company-scoped generation creates one draft with editable
`title`, `concept`, and `script`. Updates replace those fields in place. No original
script copy, feedback, publication links, frontend changes, or embeddings are added.
Existing V1/V2 unscoped recommendation endpoints retain their current behavior.

## Integrated ownership and profiles

Apply real migrations **001–008** in order; test fixtures are never migrations.
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
| `GET /ideas/{id}` | Current editable fields, generation metadata and target platforms |
| `GET /ideas/{id}/evidence` | Exact structured input supplied to generation |
| `PATCH /ideas/{id}` | Update one or more of title/concept/script; returns current idea |

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
Title/concept/script limits are 300/10,000/30,000 characters. Only draft status is
supported; migration 009 can extend it alongside feedback/publication behavior.

`history_limit` is 0–20, default 20. Supply latest titles (up to 300 characters) and
concept excerpts (up to 2,000 characters), never earlier scripts. The company/time/UUID
index supports keyset pagination and bounded generation history. This is an efficient
initial duplicate-avoidance path; it does not guarantee semantic uniqueness, search
all historical ideas, or require unique titles. No text-search index is needed yet.

## Storage and transactions

- `ideas`: owning company, current text, brief, draft status, request identity/hash,
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
version is 3 and evidence schema version is 2; increment the appropriate constant
when changing prompt semantics or captured-input shape. Structured output follows
[OpenAI's documented Pydantic Responses parsing](https://developers.openai.com/api/docs/guides/structured-outputs).

## Verification and limitations

From `backend/`, with a disposable PostgreSQL database:

```sh
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55440/postgres \
  .venv/bin/python -m unittest discover -s tests -p 'test_persistent_ideas.py' -v
```

`test_idea_integration.py` applies the actual migration sequence 001–008, including
an upgrade from populated V2 data. It runs the 007 worker with a stubbed generator
and calls the idea HTTP API using real persisted sessions and 006 ownership.
Coverage includes cross-company shared creatives, organic metric isolation,
profile/dependency revision capture, archive/session/source/profile revocation,
locks at persistence, idempotent replay and frozen evidence after profile refresh.
`test_persistent_ideas.py` additionally uses explicit test-only 006/007 stand-ins
to exercise the adapter contract, immutable storage, retries and failures.
Existing V2 database fixtures deliberately apply only 001–005.

Verified locally on 2026-09-26: all 13 focused idea integration tests passed, and
the full backend suite passed all 233 tests with `RUN_MEDIA_INTEGRATION=1` and
`HF_HUB_OFFLINE=1`. Real migrations 001–008 ran in isolated disposable schemas.
Python compilation and `git diff --check` passed. No Python lint command is configured.

OpenAI output is mocked. No paid generation, production database, live Meta refresh,
or browser UX verification is claimed. A process failure after the model call but
before commit may require another paid call after lease recovery; persistence
remains at most one idea per company/request. The bounded recent-history prompt
is duplicate avoidance, not a semantic deduplication guarantee.
