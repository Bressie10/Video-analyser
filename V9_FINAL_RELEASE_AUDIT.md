# V9 final release audit

Date: 14 October 2026. Exact audited candidate: `3a2e57a15c8318215f9fdb3373a7da5ffce14b30`. Audit branch: `codex/v9-final-release-audit`. No deployment or tag was made in this audit.

## Ancestry and candidate integrity

- `07ad7a92a67f39fca5bf7d7f9687de0355cd09ff` is the pre-V9 V8.5 baseline and an ancestor of the candidate. The full baseline-to-candidate diff is 248 files: 12 backend app, 155 offline intelligence/research, one migration, 32 backend tests, 12 frontend source, four frontend tests, ten design assets, and 22 root documents. The 25 changed production source/migration files were reviewed as the V9 attack surface. No unrelated runtime file or dependency addition was identified.
- Local and remote `v9` were initially at `be90e9099b2036cc6fa7939511c7768bc0c454b9`. They were fast-forwarded through the six Stage 8.2/8.3 commits to the exact candidate. `git rev-parse v9 origin/v9 HEAD` and `git ls-remote --heads origin v9` then all returned the exact candidate. The original checkout's unrelated uncommitted work was backed up, restored, and left outside this audit worktree.
- No runtime import of the committed `design/` concepts or absolute `/Users`/`/private/tmp` paths was found in `backend/app`, `frontend/src`, or `frontend/index.html`. Temporary source media uses `TemporaryDirectory` and is deleted after evidence packets and previews are prepared.
- The requested assertion that **no V9 production deployment occurred is false** in GitHub's deployment records. Deployment `7044373294` records a successful **Production** Vercel deployment of `b7e085b89d412e189bcedf4c6c5d0e533f31651d` at `2026-10-13T16:43:10Z`. This proves a V9 frontend deployment record, not a backend rollout, live user access, or migration 015 application. Later candidate deployments in the queried records were marked Preview. No production deployment was initiated here.

## PostgreSQL and migration gate

- PostgreSQL 17.11 (Homebrew), 114 GiB free on the data volume. macOS System V limits were `shmmni=32`, `shmmax=4194304`, `shmall=1024`. All 32 shared-memory IDs were occupied: one had six live PostgreSQL attachments and 31 owned segments had zero attachments. Both sandboxed and unrestricted `initdb` initially failed at `shmget(..., size=56)` with `No space left on device`. Only the zero-attachment segments were removed; the live cluster was untouched.
- A disposable cluster then initialized and started at `127.0.0.1:55471` with test-only `shared_buffers=8MB`, `max_connections=20`, and `dynamic_shared_memory_type=mmap`. No production PostgreSQL configuration changed.
- All ordered migrations `001` through `015` applied successfully from scratch to `v9_audit_clean` with `ON_ERROR_STOP=1`. Migration 015 created `performance_observations`; the legacy `video_performance` table remains present and unchanged by its SQL. The migrated table has 22 constraints, including composite ownership FKs and context checks; three indexes including the cohort and object lookup indexes; and insert-link plus immutable update/delete triggers. RLS is enabled with no browser-facing policy, so ordinary non-owner roles have no row access. The DB tests exercised append-only rejection, cross-company/provider identity rejection, latest version selection, and preservation of legacy rows.
- A separate disposable `v9_audit_tests` database enabled the complete DB-backed test path. Neither disposable database is production. Migration 015 has **not been intentionally deployed to production**; production schema was not queried.

## Validation results

| Gate | Result |
| --- | --- |
| Backend, database enabled, standard full suite | **600 total: 597 passed, 0 failed, 3 skipped** (the three opt-in known-sample media cases); exit 0. Those three passed separately with media enabled. |
| Real known-sample OCR/Whisper media tests | Two media-pipeline tests and one Meta-library media integration test passed in separate processes, with zero skips. A combined opt-in run reached `Ran 600 tests ... OK` but exited 134 afterward from a native `libc++` recursive-mutex shutdown error; it is **not** recorded as a clean full-suite pass. |
| Frontend full `npm test`, with `TEST_DATABASE_URL` | **335 passed, 0 failed, 0 skipped**. The formerly blocked real FastAPI/PostgreSQL integration paths ran. Browser provider responses remained fixtures. |
| Configured browser `npm run test:e2e` | **41 passed, 0 failed, 0 skipped**. |
| TypeScript `npm run typecheck` | Passed. |
| Vite `npm run build` | Passed. |
| Python `compileall` and `git diff --check` | Passed. |

There is no configured frontend or backend lint command. The first backend collection attempt failed because the existing virtual environment lacked declared `PyJWT`; `PyJWT 2.15.1` was installed into a temporary test-only path. This was an environment dependency, not a product change.

## Concrete correctness fixes

1. Six distinct ads could map to one reused video asset, making Stage 7.2 count the same creative twice. A database-backed regression reproduced `source_media_unavailable` after entering media resolution. Stage 8.1 now abstains with `insufficient_source_video_coverage` and `duplicate_video_asset` before any provider or model call when asset IDs or analyzed video IDs repeat.
2. A `206 Content-Range: bytes 100-109/100` was accepted despite an end byte outside the declared total. A focused test failed before the change and passed afterward. The media proxy now requires a positive total and `end < total`.
3. Added real-PostgreSQL tests for Creative Analysis detail ownership, cross-company lookup, stored evidence after membership loss, media-grant cookie attributes, repeated range authorization, and revocation before another range. These tests use fictional rows and a mocked provider stream.

## Security and response boundaries

- Stage 8.3 `creative_ref` is an internal asset UUID; the SQL path requires a current company assignment, matching connection/account and ad-to-video edge. Detail and each media request re-authorize current membership. A disconnected or expired connection refuses media while stored analysis detail remains available. Cross-company detail and revoked range requests were verified against PostgreSQL.
- The browser receives an allowlisted detail response and a same-origin media endpoint, never a signed Meta CDN URL. The media cookie carries the already verified application JWT, is HttpOnly, Strict SameSite, scoped to that one media path, expires in 900 seconds, and is Secure away from localhost. Provider tokens are used only by the server's Meta resolver, never sent as CDN request headers.
- Media destinations require HTTPS, an allowed Meta CDN suffix and globally routable resolved addresses; every redirect is revalidated. Invalid range syntax fails; provider `200` for a requested range fails; `206` must have coherent `Content-Length`/`Content-Range` within the requested and 500 MiB bounds. Streaming is capped at 500 MiB and five minutes; upstream response/client close in a `finally` block. Errors returned to the browser use generic text. Live CDN DNS rebinding and provider-specific redirect behavior were not exercised.
- Stage 8.2 browser projection uses pseudonymous `video_ref`, internal opaque `creative_ref`, bounded metric facts, validated citations and bounded transcript/OCR excerpts. Previews are sampled JPEGs, at most six, each at most 64 KiB and 320 pixels on its long side. Raw source media, provider IDs, account external IDs, ciphertext, tokens, prompts, raw model responses and temporary paths are not projected. Model names, elapsed time and token counts may appear in safe provenance. Browser parser also caps preview count/size.
- Production UI copy was searched for winning/causal/uplift/significance claims. The shipped comparison copy calls patterns observational associations, does not assert absence from an uncited frame, and presents experiments as tests. No new language change was needed.

## Provider, product sanity and resource gate

No owned test Meta Ads account was available (confirmed by the user). Customer data was not authorized. Accordingly **no real six-ad exact-context CTR cohort, six unique provider media resolutions, citation/counterexample review, transcript/OCR/frame/timing review, Stage 7.3 hypothesis sanity review, or supported/questionable/unsupported classification occurred**. This is not independent semantic validation.

No real Meta-backed Creative Analysis browser session occurred. Initial play, pause/resume, forward/back seek, repeated provider ranges, direct citation start, return without rerun, later re-resolution, and actual-video scene/transcript/OCR timing remain unverified. Browser fixtures exercise those UI states and navigation only. Stored evidence on unavailable media, missing transcript/OCR/scenes, insufficient cohort, no difference, hypothesis abstention, disconnected Meta, grant failure, and session errors were exercised by unit/browser fixtures or local DB paths as applicable, not live provider behavior.

Real wall time, source-media resolution/download time, Stage 7.2/7.3 latency, model-call/token counts, grant/first-byte latency, provider resolution count and bytes transferred are **unmeasured**. Code exposes bounded server provenance for media-download elapsed time and model response metadata, but there is no live sample. Re-resolution on every range was left unchanged because no evidence establishes a reliability, latency or rate-limit problem; it remains an explicit provider validation gate. No caching, queue, worker or permanent media storage was added.

Resource review found bounded temporary media lifetime, bounded previews, explicit HTTP response/client closure, transaction context managers, a single-flight UI submit lock, at most one Stage 7.2 and one Stage 7.3 model call per request, and React timeline derivations from memoized evidence. No measured runaway rerender or leak was found. Provider stream truncation and actual playback startup behavior remain unmeasured.

## Privacy and secrets scan

Only example `.env` files are tracked. Scans of production source and tests found no embedded Meta/OpenAI token, signed provider URL, customer/provider numeric account ID, or runtime local path. Design SVGs caused false positives for broad token-like regexes through encoded vector content; they are not runtime imports. Fifteen frozen Stage 5 evaluation checkpoint files contain structured model-derived `chunk_responses`/`synthesis_response` material, so a claim that the entire repository contains no model responses would be false. They are research artifacts, not browser responses or production runtime imports; their source references are local corpus identifiers. The shared Meta log filter redacts Graph and allowed CDN URL paths/queries from `httpx` INFO records; no signed URL was written to this audit report.

## Unresolved gates and production sequence

1. Obtain an owned, authorized six-creative Meta test cohort and perform the manual CTR evidence, hypothesis and playback sanity review, with aggregate non-sensitive latency/resource measurements. Decide on repeated media re-resolution only from that evidence.
2. Resolve or document the opt-in combined-suite native shutdown (`exit 134`) if that exact all-in-one command is a release gate. Its three real-media tests passed in isolation; the standard database suite is recorded separately.
3. Investigate the successful V9 Production Vercel deployment record and confirm the intended active frontend/backend/schema versions before any release action. The record must not be described as “no production deployment.”

Recommended future production order, with explicit operator approval at each deployment boundary: (1) backup and verify rollback/restore readiness; (2) apply migration 015 once, without treating rollback as a destructive drop of appended observations; (3) verify table, FKs, triggers, indexes, RLS and legacy rows; (4) deploy backend compatible with 015; (5) health and authenticated API smoke; (6) deploy frontend; (7) authenticated Creative Intelligence CTR smoke; (8) Creative Analysis detail, grant and play/seek smoke. Stop and investigate on any failed gate. No step in this sequence was executed against production by this audit.

Decision D applies because live provider validation is unavailable; the PostgreSQL migration and DB-backed test gates were completed locally.

D — code audit passes, but database/provider validation remains unavailable
