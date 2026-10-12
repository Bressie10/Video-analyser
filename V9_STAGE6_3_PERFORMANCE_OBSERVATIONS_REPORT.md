# V9 Stage 6.3 — Immutable performance observations

Base: `c21e44fb12f00b3dab17ef3363f91a266d227a14`. This stage adds historical provenance only. No comparison endpoint, frontend change, recommendation/idea integration, LLM, or semantic input was added.

## 1. Schema design

Migration `015_performance_observations.sql` adds `performance_observations` alongside the unchanged `video_performance` table. Each row has an observation UUID, company UUID, optional provider connection/account/item and video UUIDs, source, object type and exact provider object/account IDs, explicit placement scope, exposure, report dates, fetched timestamp, currency, action report time, ordered attribution windows, normalized JSONB metrics, versioned JSONB provenance, and a SHA-256 comparison-context key. Provider IDs and context fields are first-class columns; decimal metric strings and distinct action rows remain in JSONB. Cohort and object indexes support deterministic reads. Row level security defaults to denying browser table access.

The generic shape permits future organic Instagram, Facebook, and TikTok observations. Nullable Meta linkage allows a later TikTok ownership model. The insert trigger currently rejects organic rows until source-specific authorization and identity validation are implemented; there are no organic writers in this stage.

## 2. Identity and authorization

The new company ad metrics path resolves the company, persisted Meta connection, assigned ad item, and account under membership/ownership locks **before** asking Meta. The provider fetch verifies ad `id`, insights `ad_id`, ad `account_id`, insights `account_id`, and report dates. The writer repeats company assignment authorization in its insertion transaction and checks the provider IDs against the persisted ad and `act_<account>` identity. Foreign keys tie the company to the connection, account/item to that connection, and an optional video to the same connection. An insert trigger also verifies the live assignment, exact provider IDs, and exact item/video link. Cross-company reads filter by the authorized company; no caller supplied workspace ID is trusted as proof of ownership. Tokens are never stored in observations.

## 3. Immutable versions

Every successful fetch appends a new UUID row, even when its context and metrics match a prior fetch. `fetched_at` and UUID distinguish versions; the deterministic context key groups equivalent comparison contexts. A changed provider value therefore preserves the old observation. A database trigger rejects `UPDATE` and `DELETE`. This is intentional versioning rather than retry deduplication. Callers must select a version deliberately; the read repository orders each provider object by newest fetched time and UUID.

## 4. Current snapshot compatibility

The existing upload metrics route and `get_analysis`/`video_performance` shape remain unchanged. The new company route writes a current `video_performance` snapshot only if the assigned ad item has its **own direct** ContentMetric video. It never maps a shared creative asset's video to an ad-specific snapshot. Snapshot update and observation insertion share one transaction; an insertion failure rolls back the snapshot. If the ad has no direct video, the observation is still stored with `video_id=NULL` and no current snapshot is changed.

## 5. Stage 6.1 adapter and read path

`observations_for_comparison` retrieves only membership-authorized rows matching company, provider, exact provider account, placement scope, report dates, currency, action report time, and ordered attribution windows. It returns rows in provider-ID/newest-version/UUID order. `to_stage61_record` checks that duplicated payload context matches the columns, then preserves provider object/account identity, company, `meta_all_placements`, dates, currency, attribution configuration, fetched time, and metric payload. Scoring remains in Stage 6.1 Python; no comparison scores are calculated or exposed by the repository.

## 6. Migration behavior

The migration is additive, has no backfill, and does not rewrite or infer missing identities from legacy snapshots. Existing rows stay legacy. FKs use `RESTRICT` so deleting a parent cannot silently erase history. The table is append-only and provider linkage is checked at insert time; an assignment change later does not rewrite historical ownership.

## 7. Tests and limits

Mocked API tests cover authorization before provider fetch, verified Meta identity propagation, and account mismatch rejection. Unit tests cover the adapter, Stage 6.1 compatibility, context mismatch rejection, and deterministic context keys. Disposable PostgreSQL tests were added for migration application, exact field persistence, repeated versions, snapshot compatibility, rollback, trigger immutability, and cross-company isolation. They **could not run here**: both sandboxed and approved unsandboxed `initdb` failed during bootstrap with `shmget(... size=56 ...)` / “No space left on device,” indicating exhausted host shared memory rather than a SQL or application test result. Targeted Stage 6.1/6.2, Meta Ads, observation, and authorization groups passed with only database-gated skips. A full backend discovery without a database URL also reached eight older `test_v6_integration` errors because that module accesses `TEST_DATABASE_URL` without a skip guard; the non-DB run excluding that module passed: 548 tests, 282 database-gated skips, zero failures. Python compilation, privacy scan, and staged `git diff --check` passed. The migration and transactional database behavior require execution against disposable PostgreSQL before deployment.

## 8. Live-provider validation

No owned Meta session was available, so no live provider response was used. Live validation must confirm ad/account identity, combined placement scope, nullable metrics/actions, provider reporting dates, and the behavior of repeated fetches. No live IDs, names, metrics, tokens, or raw responses were committed.

A — historical provenance foundation ready for live Meta validation
