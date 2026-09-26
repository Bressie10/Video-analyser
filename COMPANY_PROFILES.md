# V3 company intelligence profiles

This isolated backend subsystem adds cached intelligence for `shared`, `instagram`,
`facebook`, and `meta_ads`. It does not implement company ownership, persistent ideas,
or UI. Recommendation endpoints remain unchanged: no inline profile generation and
no invalidation just because an idea was generated.

## Deployment and migration 006 boundary

Apply migrations 001–005, the separately maintained 006 ownership migration, then
`backend/migrations/007_company_profiles.sql`. The backend never applies migrations.
007 requires `companies(id UUID PRIMARY KEY)`; it intentionally fails without 006.
No production stub or invented assignment table is included.

Bind a `CompanyAdapter` with `bind_company_adapter(adapter)` before starting the app's
lifespan. The adapter in `backend/app/company_profile_company.py` defines two methods:

- `authorize(db, request, company_id, write=...)`: call the 006 authorization helpers,
  distinguishing read from refresh permission. Raise HTTP 401 for signed-out users,
  HTTP 404 for missing/inaccessible companies. Implement any cookie/CSRF checks here
  using the company layer's existing policy. Do not reuse connection identity as
  company identity.
- `evidence_access(db, company_id) -> CompanyEvidenceAccess`: return assigned Meta
  account UUIDs and a monotonically changing assignment generation, using the supplied
  transaction. Include explicitly authorized creative-asset accounts when relevant.
  Never return accounts merely because they share a Meta connection.

The adapter is unbound by default: profile routes return 503 and the worker does no
work. Tests use private `companies`/`test_assignments` fixtures only. Migration 006's
real helpers and session transport are not validated by this branch.

Set `COMPANY_PROFILE_WORKER_ENABLED=true` after binding the adapter and applying 007.
Default is `false`, so V2 installations still start normally. Profile workers use
`DATABASE_URL`, server-side `OPENAI_API_KEY`, and `COMPANY_PROFILE_MODEL` (fallback:
`OPENAI_MODEL`, then the existing `gpt-6-sol` default). They do not require a live Meta
access token. Request API keys are neither accepted nor stored for these jobs.

## Schema and cache semantics

| Table | Purpose |
| --- | --- |
| `company_profiles` | Unique company/scope, current revision pointer, desired versions, input/validated counters, suppression flag |
| `company_profile_revisions` | Immutable successful JSONB documents, monotonic revision number, fingerprint, assignment version, evidence manifest, platform dependencies |
| `company_profile_jobs` | Profile-owned PostgreSQL queue, attempts, captured inputs, UUID claim, lease, outcome/error |
| `company_profile_refresh_requests` | Durable profile/key → job mapping for idempotent manual requests |
| `company_profile_invalidations` | Optional company/event-key deduplication |

The pointer's composite foreign key prevents it from referring to another profile's
revision. A partial unique index permits only one queued/running job per profile.
Database triggers reject UPDATE/DELETE of successful revisions. There is no expiry
or routine deletion of revisions/idempotency records in this version. Company erasure
and retention workflows must explicitly address these retained records in later
integration; foreign keys intentionally prevent an accidental destructive cascade.

Freshness (`missing`, `stale`, `fresh`) is independent of job state
(`queued`, `running`, `completed`, `failed`). Freshness is event/version based, not a
wall-clock TTL. An ordinary refresh failure leaves the previous successful document
usable. A force request can run while that document stays fresh. A successful input
check with an unchanged fingerprint advances `validated_input_revision` without
creating or modifying a revision. Revision input counters/provenance describe its
original generation; current validation counters describe the latest successful check.

Assignment changes, unassignments, and evidence removals conservatively suppress all
four scopes immediately. Their old documents/manifests are not returned while
suppressed. Rebuilds can publish limited or empty safe profiles. Ordinary staleness
does not suppress the last successful document.

## Transactional invalidation integration

Source writers call:

```python
from app import company_profile_repository as profiles

with database() as db:
    profiles.lock_company(db, company_id)
    # Apply source changes in this same transaction.
    profiles.invalidate(
        db, company_id, ["instagram"], "analysis_changed",
        event_key="optional-unique-source-event",
    )
```

Acquire the company advisory lock before source changes. For multi-company writes,
lock company UUIDs in sorted order. Keep locks out of network/model calls. Pass one
complete event with all affected scopes; event keys deduplicate the entire event,
not individual scope invocations. Source rollback also rolls back invalidation/jobs.
The hook creates missing profile rows, atomically advances counters, and coalesces
active work. It does not inspect or implement company ownership.

| Integration point | Reason and scopes |
| --- | --- |
| Discovery adds company content | `new_content`; its platform plus any affected ad-asset platform |
| Analysis completed or replaced | `analysis_changed`; every platform referencing that analysis |
| Semantic performance change | `performance_changed`; every platform referencing that item/ad |
| Ad/creative relationship added/removed | `relationship_changed`; affected organic platform(s) and `meta_ads` |
| 006 account assignment or unassignment | `account_assignment` / `account_unassignment`; all scopes and both companies on transfer; advance adapter generation |
| Content/analysis/metric/evidence removed | `evidence_removed`; all scopes are conservatively suppressed |
| Prompt, assembly, generator or document contract upgraded | Bump `GENERATOR_VERSION` / `SCHEMA_VERSION`; worker schedules all scopes |

Platform invalidations also stale shared. Publishing a new platform revision enqueues
shared. These source-writer call sites are documented integration hooks, **not wired
into V2 connection-owned writes**. They must be connected by the company integration.
Use `evidence.semantic(old_snapshot) != evidence.semantic(new_snapshot)` as the
conservative material-change policy: every semantic value/context change matters,
while an identical retrieval with only a new `fetched_at` does not. Do not emit an
invalidation for job-state changes or idea generation.

A snapshot-consistent read captures inputs before generation. Publication checks the
claim/lease, input counter, assignment generation and platform dependencies under the
company lock. Changed inputs discard the result and requeue. The same rule protects
newer invalidations when an older generation fails. Pure content mutations without
the transactional hook are outside this contract and cannot guarantee freshness.

## Evidence and cost policy

Evidence is deterministic, newest publication first, null dates last, UUID tie-breaker.
Only existing completed analyses are read. Missing analyses remain explicitly missing;
no media downloads, embeddings, per-video LLM summaries, or backlog analysis is started.
Source candidate selection and child record loading are bounded before serialization.
Total/complete coverage counts are database aggregates, not full-history processing.

All limits live in `backend/app/company_profile_types.py`:

| Constant | Default |
| --- | --- |
| `MAX_ITEMS` | 40 content candidates per platform; Meta Ads selects at most 40 ads and 40 assigned creative assets |
| `MAX_PERFORMANCES` | 80 distinct snapshot records |
| `MAX_TRANSCRIPT_CHARS` | 2,000 per analyzed video |
| `MAX_SCENES` / `MAX_OCR` / `MAX_MOTION` | 12 / 20 / 12 records per video |
| `MAX_TEXT_CHARS` | 500 for labels, OCR text, claim text and comparison basis |
| `MAX_RELATIONSHIPS` | 3,200 ad/creative links |
| `MAX_INPUT_BYTES` | 24 KiB UTF-8 serialized evidence + instructions/schema |
| `INPUT_RESERVE_BYTES` | 256 additional assembly headroom |
| `MAX_OUTPUT_TOKENS` / `MAX_OUTPUT_BYTES` | 3,000 tokens / 24 KiB validated JSON |
| `MAX_CLAIMS` / `MAX_LIMITATIONS` | 12 per claim category / 20 limitations |
| `MODEL_TIMEOUT_SECONDS` | 60; SDK retries disabled |
| `LEASE_SECONDS` / `HEARTBEAT_SECONDS` | 120 / 20 |
| `MAX_ATTEMPTS` / `BACKOFF_SECONDS` | 3 attempts; transient retries after 30 and 60 seconds |
| `POLL_SECONDS` / `VERSION_SCAN_LIMIT` | 2 seconds / 100 companies per version scan |

Input has a hard byte budget rather than a tokenizer-dependent estimate. Output also
has the provider token limit. Oversized snapshots are omitted as whole units, not
stripped of reporting context. If needed, the largest trailing evidence unit is removed
deterministically, retaining each list's leading entries; relationships to removed
units are removed too. Coverage reports truncation and exclusions. Large platform
documents may be omitted whole from shared inputs; this is a coverage limitation.

The fingerprint includes effective bounded evidence, assignment generation, model,
generator/schema versions. Retrieval timestamps are retained as provenance but ignored
in the hash. Shared event counters/transient freshness are publication checks rather
than new intelligence, so unchanged platform revisions avoid another model call.
Change version constants whenever prompts or generator/assembly policy changes;
model-only configuration changes take effect on the next refresh, so also bump the
generator version when rolling out a model switch automatically.

A database-wide advisory lock provides one profile model slot across app processes.
Leases/claim tokens fence stale workers. Expired claims can be recovered, subject to
the attempt limit. A lost worker may already have sent a provider request; fencing
prevents its result from publishing, not retroactive cancellation of provider billing.
Permanent configuration, invalid-output, authentication and permission errors fail
without automatic retry. A new manual key can retry a terminal failure. No provider
response bodies, credentials, or raw source text are included in errors/logging.

## Document and evidence meaning

JSON documents carry topics, tone/style, recurring patterns, strong/weak themes,
repetition, shared cross-platform observations, limitations, confidence and coverage.
Claims include evidence references, an explicit comparison basis, evidence kind and
supporting count. The server validates references and computes supporting counts as
distinct cited entities (item/ad IDs or profile revisions), **not audience counts**.
Strong/weak rankings require at least two measured sources with a common known metric
and matching source/attribution/reporting/currency context. This is a conservative
comparison gate, not proof of causality or automatic verification of all model prose.

Null/absent measurements stay unknown; zero stays zero. Paid and organic measurements
are separate and never summed. Ad snapshots are keyed once by ad item UUID; shared-ad
attribution remains ad-level regardless of the number of visible creative assets.
All stored reporting context survives platform evidence and revision provenance.

Shared inputs consist of platform revision documents plus a deduplicated evidence
registry with source/version hashes and measurement context. They do not resend raw
analysis history. If platform revisions describe conflicting versions of the same
source, the registry flags it and excludes it from automated comparison eligibility.
Missing/stale platform coverage remains explicit. Empty evidence, including an entirely
empty shared profile, creates an insufficient-coverage document without a model call.

User preference/feedback is a separate document category and evidence kind. This
version has no preference source and rejects invented preference claims. Model output
is JSON-mode data validated locally against the document model; incomplete/oversized
responses fail. See the official [Responses structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## API

All routes require 006 company authorization and return `Cache-Control: private, no-store`.

- `GET /api/companies/{company_id}/profiles`: four status objects, no model or enqueue.
- `GET /api/companies/{company_id}/profiles/{scope}`: status plus usable current document,
  immutable revision metadata, coverage and evidence manifest. No historical-read API.
- `POST /api/companies/{company_id}/profiles/{scope}/refresh`: requires a 1–128 character
  `Idempotency-Key`, no request body, returns HTTP 202 with `job_id`, `coalesced` and
  `idempotent_replay`. Poll the read endpoint's `job` field for state/outcome/error.

This POST is the backend force-refresh capability: it expedites a queued job or
coalesces into an existing build, but **does not bypass unchanged-input reuse**. A key
replays its original job even after completion/failure; use a new key for a new request.
Shared refresh first queues stale/missing platforms, waits for active platform work,
and can build a partial document after a platform reaches terminal failure.

The repository read contract can be used later by company recommendation code to
consume bounded cached profiles. Recommendation reads must not call `refresh`, the
generator, evidence assembly or source invalidation.

## Verification

From `backend`, using the existing dependencies and a disposable PostgreSQL database:

```sh
TEST_DATABASE_URL=postgresql://USER@127.0.0.1:PORT/postgres \
  .venv/bin/python -m unittest discover -s tests -p test_company_profiles.py -v
```

The suite applies 001–005 + a test-only company stub + 007 per isolated schema. It
exercises the actual SQL, API, queue, background thread and publication path. Existing
V2 suites remain pinned to migrations 001–005 until real 006 integration testing is
available. Provider calls are fake; tests do not validate live model access/quality,
production ownership helpers, real account assignments or deployment. No frontend or
video-processing behavior changed, so browser/media acceptance is outside this change.
