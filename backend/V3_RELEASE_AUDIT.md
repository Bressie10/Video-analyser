# V3 backend/database release audit — 2026-09-27

Audited `f162ccf` on `codex/v3-final-audit`. Three corrections were necessary:

1. **Creative-access revocation left cached profile evidence usable.** Reproduced
   with the production ad importer: after A's assigned ad stopped referencing a
   creative, A's current library reader denied that creative but Facebook, paid and
   shared profile endpoints still returned it. Ad import now resolves external
   data before locking the connection, then changes edges and invalidates the
   assigned company's profiles atomically. Removal suppresses all its scopes;
   addition stales them; unchanged discovery is a no-op. Connection locks serialize
   edge changes against ownership reads and final idea persistence. Failed
   invalidation rolls back discovery; running profile workers are fenced by input
   counters. Ordinary content/metric freshness remains explicitly refreshed.
2. **Refresh idempotency could refer to another profile's job.** A direct INSERT
   with profile A and job B passed both independent FKs; A's HTTP refresh replay
   returned B's job UUID. Migration 010 adds UNIQUE(profile_id,id) to profile jobs
   and replaces the request's job-only FK with a validated composite profile/job
   FK. Valid history survives the upgrade; inconsistent data causes atomic failure,
   not silent repair. No other schema change or speculative index was added.
3. **Archived-company ownership releases were still permitted.** The former 006
   contract allowed release/reassignment while archived, contrary to this audit's
   fail-closed mutation criterion. Four ownership mutations now require an active
   company. Their regression verifies denial while archived and success after
   restoration; retained data and the explicit restore operation are preserved.

Migrations **001–010**, including the justified integrity correction, form the
final audited V3 schema. Migrations 006–009 themselves were not rewritten.

## Foreign-key and historical-record review

All 46 foreign keys in the fully migrated disposable schema were inspected via
`pg_constraint` / `pg_get_constraintdef`; this includes pre-V3 relationships.

| Migration / relationships | Integrity and update/delete behavior |
| --- | --- |
| 006 library→account/video, account→initial run | Composite UUID+connection FKs; NO ACTION; intentionally NOT VALID for historical rows |
| 006 job→run/item | Composite UUID+connection FKs; DELETE CASCADE for dependent jobs; intentionally NOT VALID |
| 006 company→connection | DELETE RESTRICT; company records survive disconnect |
| 006 company account→company/account | Composite company/connection and account/connection/platform FKs; DELETE RESTRICT; organic account ownership is uniquely constrained |
| 006 ad assignment→company account/item | Composite company/connection/account/platform and item/connection/account/type FKs; DELETE RESTRICT; one company per assigned ad |
| 007 profile→company, revision→profile | NO ACTION; revisions reject UPDATE/DELETE; profile current-revision pointer uses a same-profile composite FK |
| 007 job→profile, refresh→profile, invalidation→company | NO ACTION; refresh's job relationship is tightened by 010 |
| 008 generation request→company; idea→company/request | NO ACTION; company/request/hash composite FK and company/request uniqueness enforce replay identity |
| 008 sources/performance/targets→idea | NO ACTION; sealed evidence triggers reject later INSERT/UPDATE/DELETE |
| 008 source→performance mapping | Two same-idea composite FKs prevent cross-idea attribution |
| 009 publication→idea/item | DELETE RESTRICT; composite association PK makes duplicate links idempotent; company scope is inherited from immutable idea ownership |
| 010 refresh→job | Same-profile composite FK, validated on existing data; NO ACTION |

All FK updates use NO ACTION. The five NOT VALID 006 constraints still enforce
new or changed relationships; legacy inconsistent rows are preserved and scoped
readers independently verify connection consistency. No blanket validation/repair
was attempted. The upgrade tests exercise these legacy rows explicitly.

Selected source/performance UUIDs and idea profile revision UUIDs are intentionally
historical provenance rather than live access grants. Source snapshots and profile
payloads are frozen; missing live-source FKs preserve their history after unlink or
source removal. The service captures the real authorized profile revision and
validates source/metric ownership again before save. Publication rows use live
entity FKs but never ownership-assignment FKs, so reassignments cannot move their
owning idea or destroy the association. Reads return only internal item UUIDs and
link timestamps, with no live metadata/metrics join.

## Scope, compatibility and code review

- 006 direct ownership and content-only creative access remain distinct. Sibling
  ads and another company's organic metrics are excluded by scoped readers.
- Current profile access suppresses revoked evidence; historical idea evidence is
  reachable only through its original company/idea route. Lifecycle, feedback,
  text edits and publication mutations cannot alter generation inputs.
- The claim row lock, claim UUID fencing and company/request unique constraint
  prevent duplicate ideas. Replays return current edited state after source unlink.
- The default profile and idea adapters both use persisted Meta sessions and the
  real ownership repository. Their request/worker/evidence responsibilities differ;
  the shared ownership SQL is authoritative. Test overrides and the explicitly
  test-only company contract are exercised, not dead production fallbacks.
- Existing V2 route shapes and provider-ID-free projections remain unchanged.
  Publication association is never used to authorize a live library read. Scoped
  responses contain internal UUIDs, not provider identities/URLs or credentials.
- Both profile and Meta worker lifespans remain wired. Profile claim/lease recovery,
  shared dependencies, unchanged-input reuse and archived generation are covered.
- No V4 UI, new auth, auto-publication, fingerprinting or unrelated cleanup added.

## Query/index review

Reviewed ownership scope/evidence SQL, latest profile job, queue claim, company idea
history, idempotency, frozen-evidence reads and publication lookup/delete. Existing
PK/composite/partial indexes cover the bounded operational queries. The only added
index is the unique pair required by 010's composite FK.

An isolated EXPLAIN (ANALYZE, BUFFERS) probe used 20,000 completed profile jobs,
5,000 sealed ideas and 2,000 extra library items:

| Actual query | Observed execution | Plan evidence |
| --- | --- | --- |
| Latest job for profile | 0.570 ms | Uses `company_profile_jobs_profile_key`, bounded profile candidates + sort |
| Recent company idea/feedback history | 0.025 ms | Uses `ideas_company_history` |
| Selected company content | 1.847 ms | Scoped CTE scan/hash joins; no justification for a speculative new index |
| Profile queue claim | 0.022 ms | Uses `company_profile_jobs_ready` |

These are local synthetic measurements, not a production performance guarantee.
Revisit plans with production cardinalities before adding any further indexes.

## Final verification

| Check | Result |
| --- | --- |
| Newly created empty PostgreSQL database | 001→009→010 all passed; 29 application tables; database removed after the check |
| Populated V2 upgrade | 006→009→010 passed; original data and intentionally inconsistent historical rows preserved |
| Populated sealed V3/008 upgrade | 009 passed with original idea fields/evidence unchanged |
| Populated refresh records → 010 | Valid records preserved; invalid cross-profile records rejected with transactional DDL rollback |
| Focused ownership/profile/idea/feedback/publication/audit suites | 139 passed |
| Full backend with disposable PostgreSQL and local media enabled | 267 passed, zero skipped; V2 recommendation/API regressions included |
| Frontend TypeScript and production build | Both passed |
| Existing frontend browser suite | 41 passed, zero skipped |
| Browser → real FastAPI → workers/media → PostgreSQL → recommendation | 1 passed on 001–010; includes 320px overflow check |
| Compilation and diff whitespace checks | Passed; no configured Python/frontend lint command |

Commands used from `backend/` (local disposable database URL supplied through
`TEST_DATABASE_URL`):

```sh
PYTHONPATH=tests .venv/bin/python -m unittest test_company_ownership test_company_profiles test_company_profile_integration test_persistent_ideas test_idea_integration test_idea_feedback_publications test_v3_release_audit -v
RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -s tests -v
```

From `frontend/`: `npm run typecheck`, `npm run build`, `npm run test:e2e`, and
`HF_HUB_OFFLINE=1 npm run test:integration` with `TEST_DATABASE_URL` set. The real
browser integration creates its own disposable database and now applies the entire
V3 migration chain, while keeping external Meta/OpenAI boundaries fixture-controlled.

Recommendation: **ready to merge into `v3` with migration 010 included**. Nothing was
pushed or merged during this audit. This is repository release verification, not
production deployment or live-provider certification.

## Remaining limits

- Ordinary new-content/analysis/metric changes still need explicit profile refresh;
  ownership and creative-access revocations are transactionally integrated.
- Meta and OpenAI boundaries are mocked in automated tests. Real media processing
  uses known generated fixtures and cached OCR/Whisper models; this does not prove
  provider permissions, production model availability or production deployment.
- Five legacy NOT VALID constraints require an explicit data-remediation plan before
  validation. Migration 010 deliberately rejects inconsistent old refresh mappings.
- A provider call that succeeds before a failed idea save may be charged again on
  retry. Persistence remains one idea per company/request.
- Historical links restrict entity deletion until explicitly removed. They do not
  publish content, verify causal attribution or grant current content access.
