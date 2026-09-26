# V3 company intelligence profiles

This backend subsystem adds cached intelligence for `shared`, `instagram`,
`facebook`, and `meta_ads`, integrated with migration 006's explicit company ownership.
It does not implement persistent ideas or UI. V2 recommendation endpoints remain
unchanged: no inline profile generation and no invalidation from generating an idea.

## Deployment and ownership boundary

Apply the integrated release migrations 001–010 in order, running only missing
files on existing installations. Migration 007 adds profiles; 010 tightens refresh
job integrity. The backend never applies migrations automatically. Ownership
operations require the profile invalidation hook and roll back if it is unavailable.
Migrations do not backfill guessed company ownership.
The historical `NOT VALID` constraints from 006 remain unvalidated and unrepaired.

`backend/app/company_profile_company.py` binds `OwnershipCompanyAdapter` by default:

- HTTP authorization resolves the existing persisted Meta session cookie in the
  request transaction, then calls 006's `require_active_company` with the authenticated
  connection ID. Missing/expired/disconnected sessions return 401; unknown, foreign,
  or archived companies return 404. A connection may access all of its active
  companies; there are no users, memberships, or per-company permission tiers.
- Trusted profile jobs resolve their persisted company to its owning connection and
  use the same active-company helper. Linked account IDs are provenance only.
  Evidence queries reuse 006's `COMPANY_SCOPE_SQL`, including explicit ad assignments,
  sanitized creative metadata, and connection checks at each relationship.
- The adapter's version is a deterministic hash of effective account links and ad
  assignments. It is not an event counter. Transactional profile `input_revision`
  counters fence access changes, including removal followed by restoration, while
  identical effective ownership/evidence can reuse an immutable successful revision.

An explicit `bind_company_adapter(None)` still fails closed (503/no worker generation).
There is no production ownership stub or fallback to connection-wide content.

Persistent OAuth sessions now use cookie `Path=/api` so the same session reaches both
`/api/meta` and `/api/companies`. Secure, HttpOnly, and SameSite=Lax remain in place.
Reconnect clears the old `/api/meta` cookie; disconnect clears both paths. Existing
browsers with only the old cookie must reconnect once to use company routes. Legacy
in-memory Meta sessions retain their original transport and cannot authorize profiles.

Set `COMPANY_PROFILE_WORKER_ENABLED=true` after applying the full migration chain to enable the background
worker. Default is `false`. Workers use `DATABASE_URL`, server-side `OPENAI_API_KEY`,
and `COMPANY_PROFILE_MODEL` (fallback: `OPENAI_MODEL`, then `gpt-6-sol`). They do not
need a live Meta access token. Request API keys are neither accepted nor stored.
Archived companies are excluded from claims/version scheduling; restore invalidates
and resumes their work. Model calls remain outside database transactions.

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

The lock order is connection row, company advisory lock, then profile/job rows.
`profiles.lock_company` takes a shared connection lock before the advisory lock.
Ownership operations take an exclusive connection lock before mutations and invoke
invalidation in that same transaction. For other source writers, acquire
`profiles.lock_company` before source changes. For multi-company writes, lock
company UUIDs in sorted order. Keep locks out of network/model calls. Pass one
complete event with all affected scopes; event keys deduplicate the entire event,
not individual scope invocations. Source rollback also rolls back invalidation/jobs.
The hook creates missing profile rows, atomically advances counters, and coalesces
active work. It does not inspect or implement company ownership.

| Integration point | Reason and scopes |
| --- | --- |
| Discovery adds company content | `new_content`; its platform plus any affected ad-asset platform |
| Analysis completed or replaced | `analysis_changed`; every platform referencing that analysis |
| Semantic performance change | `performance_changed`; every platform referencing that item/ad |
| Ad/creative relationship added/removed | **Bound in ad discovery**: additions stale all owner scopes; removals suppress all owner scopes with `evidence_removed` |
| 006 account link/unlink or organic reassignment | **Bound**: `account_assignment` / `account_unassignment`; suppress all scopes, both companies on transfer |
| 006 ad assign/unassign/reassign | **Bound**: same restrictive reasons; suppress all scopes for the affected company, both companies on transfer |
| 006 archive/restore | **Bound**: `evidence_removed` / `account_assignment`; suppress all scopes; archived companies cannot read or refresh |
| Content/analysis/metric/evidence removed | `evidence_removed`; all scopes are conservatively suppressed |
| Prompt, assembly, generator or document contract upgraded | Bump `GENERATOR_VERSION` / `SCHEMA_VERSION`; worker schedules all scopes |

Platform invalidations also stale shared. Publishing a new platform revision enqueues
shared. Ownership hooks are bound in `company_ownership_repository.py`; no-op links,
assignments, releases, or archive/restore calls do not invalidate. An unrelated
company is not invalidated, including when it shares an Ads account.
Ad discovery now treats creative edges as company access grants. It resolves
provider data first, locks the connection before changing edges, and invalidates
only the ad's assigned company in the same transaction. Removed edges suppress
cached profiles and fence running builds; an invalidation failure rolls back the
edge changes. Repeated identical discovery does not invalidate. Standalone V2
schemas without company assignments retain their existing behavior.

Other new-content, analysis and metric hooks remain documented integration points,
not automatically wired into V2 source writes. Request an explicit profile refresh
after those changes. Refresh rechecks effective evidence without rerunning media
analysis. This limitation affects freshness; creative-access revocation is handled
transactionally and does not wait for a manual refresh.
Use `evidence.semantic(old_snapshot) != evidence.semantic(new_snapshot)` as the
conservative material-change policy: every semantic value/context change matters,
while an identical retrieval with only a new `fetched_at` does not. Do not emit an
invalidation for job-state changes or idea generation.

A snapshot-consistent read captures inputs before generation. Publication checks the
claim/lease, input counter, effective ownership fingerprint and platform dependencies under the
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

The fingerprint includes effective bounded evidence, effective ownership fingerprint, model,
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

Migration 008/company recommendation code must authorize its authenticated connection
with `ownership.require_active_company(db, connection_id, company_id)`, then take
`profiles.lock_company` and call `profiles.read` in that transaction. Consume only
`usable` documents; ordinary stale successful revisions can remain usable, but
ownership-suppressed revisions cannot. Do not read revision history directly or use
V2 connection-wide performance helpers. Recommendation reads must not call `refresh`,
the generator, evidence assembly, or source invalidation. Persisted ideas must respect
subsequent ownership revocation rather than treating an old profile manifest as an
access grant. No migration 008 tables or behavior are implemented here.

## Verification

From `backend`, using the existing dependencies and a disposable PostgreSQL database:

```sh
TEST_DATABASE_URL=postgresql://USER@127.0.0.1:PORT/postgres \
  .venv/bin/python -m unittest discover -s tests -p test_company_profiles.py -v
```

The profile suites apply the real 001–010 migrations and use the actual ownership
adapter and persisted Meta sessions. Existing profile-cache tests seed initial links
directly to keep their queue assertions isolated; focused integration tests exercise
all real ownership mutation hooks. Standalone V2 database/API fixtures retain
001–005 coverage; OAuth and full-stack fixtures additionally exercise V3 schemas.

`test_company_profile_integration.py` covers two companies on one connection, separate
organic content, shared Ads accounts/creatives, metrics/metadata isolation through
platform and shared profiles, transactional invalidation, no-op/rollback behavior,
archive/restore, concurrency, and foreign/unauthenticated access. Ownership upgrade
tests preserve populated V2 fixtures through the complete migration chain. The V2 OAuth fixture verifies
cookie transport into company routes and cookie cleanup on disconnect.

Run the full backend suite with `python -m unittest discover -s tests -v` and
`TEST_DATABASE_URL` set. Provider/model calls are stubs; live model quality, production
migration locking, and deployment remain unverified. The final audit also verifies
the existing V2 browser/media flow on the fully migrated database.


## Release audit corrections

Migration 010 validates the composite `(profile_id, job_id)` refresh relationship;
independent foreign keys previously allowed a refresh key to replay another
profile's job UUID. The supporting unique job key also supports lookup by profile.
Archived companies now reject account/ad release and reassignment as well as new
assignments. Restore the company before making ownership changes. Restoration,
read-only company lookup and retained historical records remain supported.
See [the final V3 audit](backend/V3_RELEASE_AUDIT.md) for verification and remaining
operational limits.
