# V9 Stage 6.4 — Performance History Validation Gate

## Scope and revisions

- Exact base: `014852a1cf9433b40562d967d24701bdc3fa496e`.
- Audited Stage 6.4 code head: `a3244c540d70d2c88f852ddb2b0f83a0bbfbe672`. This report is a subsequent documentation-only commit on `codex/v9-stage6-performance-validation`.
- Integration audit starts at `1dc11b6b23a40442e9602dae9c2b859ab45bde69` and follows the linear Stage 6.1, 6.2, 6.3, and 6.4 commits. No deploy or tag was made.

## PostgreSQL and migration 015

The only database used was the local, explicitly disposable PostgreSQL database `v9_stage64_disposable_20261012` on `127.0.0.1:5432`, supplied to test processes through `TEST_DATABASE_URL`. Tests created and dropped clean, uniquely named schemas. No production database or provider credentials were used. The host could not bootstrap a second cluster because of a shared-memory limit; an already running local PostgreSQL server hosted this isolated test database.

Every migration from 001 through `015_performance_observations.sql` applied in order to a clean schema. Catalog checks confirmed all 21 observation columns and their expected types, eight foreign keys to company, Meta account/item, and video tables, the primary/cohort/object indexes, enabled RLS with no table policy, and the insert-link and update/delete-rejection triggers. A legacy video and current performance row inserted before migration 015 survived with their original values. The new history table was empty after migration: no backfill was fabricated. RLS is defense in depth; repository authorization and company predicates remain necessary for the table-owning application role.

## Persistence, isolation, and comparison

- **Successful transaction:** An authorized assigned ad produced one historical row with exact provider object/account identity, all-placement scope, report dates, currency, ordered attribution windows, and action report time. Its directly linked video snapshot updated in the same transaction.
- **Rollback and immutability:** Forcing observation insertion to fail after snapshot mutation left no new history row and restored the prior snapshot. Direct SQL `UPDATE` and `DELETE` were rejected by the append-only trigger.
- **Repeated versions:** Two fetches of one ad retained distinct UUIDs and fetch times, unchanged earlier metrics, and the same deterministic context key.
- **Authorization:** Real repository and database calls excluded another company's observations, denied a foreign assignment, wrong provider ad/account ID, wrong connection, and an unassigned ad. A direct insertion with a different video from the same connection was rejected by the identity/link trigger.
- **DB to Stage 6.1 round trip:** Six synthetic ads were stored under one exact comparison query, read through `observations_for_comparison`, converted with `to_stage61_record`, and compared deterministically. The target was excluded and five distinct peers were eligible; reducing the peers below five caused abstention.
- **Latest version:** The repository continues to retain every fetch as history. `latest_observations_for_cohort` selects at most one newest row per provider object before adapter conversion or metric eligibility. Re-fetching a peer with a missing metric left the older metric in history but reduced the usable peer cohort to four, causing abstention. UUID breaks equal-timestamp ties deterministically. This helper is the required construction step for any future historical comparison caller; no product caller currently invokes comparisons.

## Regression and integration audit

- Stage 6.1, Stage 6.2, Stage 6.3, DB-backed migration/observation, Meta Ads, company authorization, performance, recommendation, and motion-gate tests were included in the complete backend run: **558 tests, zero failures, three skips**. The three skips require local OCR/Whisper models and are unrelated to the DB gate. The final exact-eight-FK assertion was also rerun separately and passed after its test was tightened.
- Separate backend non-DB run: 256 tests across 38 modules, zero failures, two skips. Focused DB rerun of the legacy performance and Stage 6.4 observation tests: five tests, zero failures/skips.
- Python compilation passed. Privacy scan of the Stage 6.4 diff found no credential or long provider-ID patterns. `git diff --check` passed. No frontend build or browser QA was needed because no frontend file changed.
- The first complete DB run had four assertions fail inside one legacy performance test: it expected stored legacy motion events to be sent to the recommendation model. The established downstream motion gate removes them from model input while preserving stored data. The assertion now checks that exact contract; the focused DB rerun passed. These were stale test expectations, not persistence failures.

The production files changed across the audited Stage 6 chain are `backend/app/meta_ads.py`, `backend/app/meta_ads_routes.py`, `backend/app/performance_observation_repository.py`, `backend/app/video_repository.py`, `backend/intelligence/observation_adapter.py`, `backend/intelligence/performance_comparison.py`, `backend/intelligence/real_meta_history.py`, and `backend/migrations/015_performance_observations.sql`. There are no frontend changes. The comparison remains offline and observational, with paid and organic contexts separated and no composite score or causal conclusion. Stage 5 semantic output is absent. No comparison import or call reaches recommendations or idea generation. The Stage 6.4 diff contains only the adapter selection helper, database tests, a corrected legacy test assertion, and this report; no real customer identifiers, metrics, names, tokens, or raw responses were added.

## Live Meta and remaining checks

The production route orders the flow as company ad authorization, Meta ad/account identity verification, ad Insights retrieval, immutable observation insertion, optional current snapshot update, and authorized historical read. The provider call occurs outside the write transaction; the writer repeats authorization and identity checks under transaction locks. No authorized live Meta connection was available for a smoke test. Live provider behavior remains unverified and is an external post-integration check. No database or comparison blocker was found in the disposable validation.

A — Stage 6 performance foundation is ready to integrate into v9; live Meta validation may remain a post-integration external check
