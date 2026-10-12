# V9 Stage 6.2 — Real owned Meta Ads history feasibility

Base: `2f75f182207250181a33e418e7d5d28bd22a8a14`. This is a read-only, offline research audit. No live Meta session, Meta configuration, or database URL was available in the execution environment. Therefore **no owned-history API request was made**, and live field supply, cohort size, metric comparability, CTR differences, and action diversity remain unverified. Mocked tests prove code-path behavior only.

## API-to-comparison field mapping

“Available” below describes the inspected request and conversion path, not an observed live response. Meta may omit individual metric values. The selected company/workspace is caller supplied and must be authorized by a future production integration; it is not a Graph Insights field.

| Comparison dimension | Existing source / handling | Status |
| --- | --- | --- |
| Workspace/company identity | Caller or company ownership tables, outside `ad_performance` | Derivable with authorization; absent from legacy ad snapshot |
| Meta ad account ID | `me/adaccounts` returns `act_<id>`; ad identity and insights return numeric `account_id` | Directly available; currently discarded before `video_performance` persistence |
| Ad ID | Discovery `id`, ad identity `id`, insights `ad_id` | Directly available; currently discarded before `video_performance` persistence |
| Provider identity | `performance_source=meta_ads` | Directly available and persisted |
| Report date range | Explicit `time_range`; insights `date_start/date_stop` checked | Directly available and persisted in Meta JSON |
| Currency | Insights `account_currency` | Directly available when returned; nullable in current Meta JSON |
| Impressions, reach, clicks | Ad Insights fields | Directly available when returned; persisted in Meta JSON |
| Spend, CTR, CPC | Ad Insights decimal fields | Directly available when returned; persisted as decimal strings in Meta JSON |
| Action rows | `actions`, `conversions`, `video_play_actions` with `action_type` | Directly available when returned; persisted without merging types |
| Action attribution windows | Request fixes `7d_click`, `1d_view`; each row retains separate values | Request-derived configuration, persisted in Meta JSON; individual values may be absent |
| Action report time | Request fixes `impression` | Request-derived configuration, persisted in Meta JSON |
| Publisher platform / placement scope | No `breakdowns=publisher_platform` in request and no publisher field in selected output | Individual Facebook/Instagram placement unavailable; combined query scope derivable from request and currently discarded before persistence |
| Fetched timestamp | `video_performance.fetched_at` | Already safely persisted in table, but omitted by `get_analysis` response |

## Placement model and Stage 6.1 correction

**Option A: `meta_all_placements`.** The current `level=ad`, `time_increment=all_days` request has no publisher-platform breakdown. Its single row covers the selected ad's eligible Meta delivery in that query; the request gives no evidence for calling it Facebook-only or Instagram-only. The [Meta Business SDK's Insights field definitions](https://github.com/facebook/facebook-php-business-sdk/blob/main/src/FacebookAds/Object/Fields/AdsInsightsFields.php) distinguish `publisher_platform` as a breakdown, not an ordinary selected metric. The offline contract now requires the explicit combined scope and compares only identical scope values. Option B would change row cardinality and require separate checks of metric/action availability, dates, and attribution windows. It is less safe for this first experiment and was not added. Stage 6.1's previous requirement for an explicit Facebook or Instagram paid platform was corrected narrowly; organic platform rules and `MIN_COHORT=5` are unchanged.

## Cohort and experiment

The collector requires one caller-selected owned ad account, one workspace identity, and one exact date range. It pages through the existing discovery functions, sorts exact provider ad IDs, checks each ad's account identity, and uses the existing ad-level insights request. It includes all discovered ads regardless of performance, keeps records in memory, and records aggregate exclusions. At least six distinct eligible ads are required so each target can have five peers. If eligible, the first three sorted IDs are targets; Stage 6.1 runs independently for impressions, reach, clicks, spend, provider CTR, provider CPC, CPM, frequency, and derived click rate. Action comparisons are attempted only for observed collection/type/window combinations and remain subject to five eligible peers. Types and `7d_click`/`1d_view` are never combined.

| Real-data measure | Finding |
| --- | --- |
| Ads discovered / usable / eligible / excluded | Not measured: no owned Meta session |
| Aggregate exclusion reasons | Not measured; mocked cases exercise account mismatch, malformed report, missing currency, and insufficient cohort |
| Metrics actually comparable | Not measured |
| Provider CTR vs `clicks / impressions × 100` | Not measured; separate metrics remain separate |
| Provider CPC denominator vs generic `clicks` | Unproven. `spend / clicks` is not labeled equivalent to provider CPC |
| Action-type diversity | Not measured; collector counts exact collection/type combinations without emitting identifying rows |

## Persistence and provenance gap

`video_performance` is one mutable snapshot per video. Its `meta_ads` JSON retains metric values, date range, currency, and requested attribution configuration; `fetched_at` exists on the table. The current `ad_performance` path verifies exact ad and account IDs but drops both before `performance_snapshot` and `save_performance`. The legacy ad metrics route checks video ownership by user, not a company-scoped ad assignment. The library has separate ad-item and company-assignment relationships, but this snapshot cannot be safely rejoined to a unique ad history after those IDs are lost. Combined placement scope is implicit in request code and is not persisted. A refresh overwrites the prior report window and metrics. Safe historical cohort reconstruction from current `video_performance` alone is therefore impossible.

Proposed future persistence contract only: immutable observation keyed by authorized company/workspace ID, provider ad ID, exact Meta ad account ID, provider, explicit placement scope, report start/end dates, fetched timestamp, currency, action report time, exact ordered attribution configuration, raw nullable provider metrics, and typed action rows with separate window values. Keep source request/version provenance and authorization linkage; reject duplicate ad-context observations or version them deliberately. No migration or production writer is included here.

No **live** account names, account IDs, ad IDs, customer metrics, access tokens, or raw API responses were committed. Test identifiers and values are synthetic. Real-data artifacts: none.

## Decision

D — insufficient owned historical data to evaluate
