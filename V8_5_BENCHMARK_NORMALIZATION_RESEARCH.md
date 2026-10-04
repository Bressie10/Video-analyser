# V8.5 benchmark and performance normalization research

This is offline research, not a production scoring policy. `backend/intelligence/normalization.py` consumes validated `BenchmarkVideo` documents without changing the frozen V8.5 contracts. No provider data was acquired for this work. Provider meanings below are limited to what the repository's request fields and comments establish; the exact platform counting rules, revisions, and availability require later provider-documentation verification.

## Current available signals

The V8 common snapshot stores `view_count`, `like_count`, `comment_count`, and `share_count` as nullable nonnegative counts and a separate `performance_source`. Optional organic library fields `reach` and `impressions` are added in `meta_library_metrics.py`; ad details live in `meta_ads` JSON with a date range and attribution context. These are retrieved snapshots, not a performance time series. A null or missing value is unknown, not zero. Storage of TikTok performance remains represented by the legacy `tiktok_video_performance` migration and the current TikTok query path; it is not evidence of a comparable external benchmark set.

| Provider/context | Provider field → local field | Known definition and type | Comparability limitation |
| --- | --- | --- | --- |
| Instagram organic Reel/video | `views` → `view_count` | Lifetime insight count requested in `instagram.py` | Exact view qualification is not defined here; cannot equate to Facebook plays or ad three-second views. |
| Instagram organic Reel/video | `likes`, `comments`, `shares` → corresponding `*_count` | Lifetime insight counts | Platform action definitions and visibility can differ. |
| Instagram organic | `reach` → `reach` | Lifetime exposure metric from `meta_library_metrics.py`; generally unique reach, but precise provider basis is not recorded in V8 | Do not infer impressions or viewing from reach. |
| Facebook organic Page video | `total_video_views` → `view_count` | Lifetime video view count | Threshold is not documented in repository. |
| Facebook organic Page video | `total_video_reactions_by_type_total.like` → `like_count`; `total_video_stories_by_action_type.comment/share` → counts | Lifetime reaction/action counts; only explicit Like reactions are included | Other reaction types are excluded. |
| Facebook organic Page video | `total_video_impressions` → `impressions`; `total_video_impressions_unique` → `reach` | Lifetime exposure counts | Impression and unique impression concepts differ; not equivalent to views. |
| Facebook organic Reel | `fb_reels_total_plays` → `view_count` | Lifetime plays count | Plays are not established as the same event as video views. Reel reach/impressions are not fetched by the library helper. |
| Facebook organic Reel | `post_video_likes_by_reaction_type.REACTION_LIKE`; `post_video_social_actions.COMMENT/SHARE` → counts | Lifetime action counts | These use different provider fields from Page video actions. |
| Meta Ads, paid | `actions.video_view` → `view_count` | Repository comment identifies Meta's three-second video view | Reporting is ad-level, date-ranged and impression-time attributed; not organic views. |
| Meta Ads, paid | `impressions`, `reach`, `clicks`; `spend`, `ctr`, `cpc`; `actions`, `conversions`, `video_play_actions` → `meta_ads` details | Exposure/click counts, monetary and rate fields, action breakdowns; attribution windows `7d_click` and `1d_view` retained separately | Currency, attribution, placement, spend and objective affect interpretation. Overlapping actions/windows must not be summed. |
| TikTok account video | `view_count`, `like_count`, `comment_count`, `share_count` → same local names | Counts from authorized video query/list; `create_time` and duration can be listed | This repository does not define TikTok's count qualification or measurement window. No reach/impressions/follower baseline is supplied. |

The V8 `performance.py` mapping and database columns erase provider-specific field names in the common count projection. A future benchmark import should attach exact raw field, provider API/version, metric definition, window, and retrieval time to each `BenchmarkVideo` metric. The frozen schema supports semantic definitions but cannot recover definitions lost in old V8 snapshots.

## Comparability matrix

| Pair or use | Classification | Evidence boundary |
| --- | --- | --- |
| Repeated snapshot of the same provider field, media type, exposure, account and defined measurement basis | Directly comparable as a count under the stated definition | Only if observation windows and publication ages are aligned; a later snapshot accumulates more opportunity. |
| Instagram `views` across Instagram Reels with the same source definition | Conditional | Same named field, but distribution, format and age still matter. |
| Facebook `total_video_views` across Page videos; `fb_reels_total_plays` across Reels | Conditional within each field | Keep videos and Reels separate. |
| Likes/comments/shares within one provider field and exposure class | Conditional | Engagement opportunity and action availability can vary. |
| Reach or impressions across media from the same exact provider field | Conditional | They measure exposure; unique reach and total impressions are different. |
| Instagram views vs Facebook views/plays vs TikTok views | Not safely comparable | No shared qualification definition in repository. |
| Any organic count vs Meta Ads count | Not safely comparable | Paid distribution and ad attribution change exposure and event definitions. |
| Views/plays vs reach/impressions | Not safely comparable | View events, unique audience, and exposure events answer different questions. |
| Likes vs all Facebook reactions; action or conversion totals from different attribution windows | Not safely comparable | Local Like excludes other reactions; ad action windows may overlap. |

The offline peer-video code checks platform, account ID, performance source, organic/paid exposure, content type, declared format, attribution context, and full metric definition equality. It also requires explicit publication-to-fetch observation windows and publication ages within two days. `unknown` and `mixed` exposure, missing identity/type/window, and known mismatches are ineligible. A null declared format or attribution context is carried as an explicit limitation, never silently treated as proof of compatibility. Equal free-form metric definitions and source names remain only a declared match, not independently verified provider semantics. This conservative gate does not claim that passing records are causally or statistically exchangeable.

## Candidate experiments

For peer-video cohorts, the harness excludes the target and exact provenance aliases, evaluates each candidate's context, then deduplicates eligible records by exact platform/provider ID or platform/public URL. A record containing both identifiers can link ID-only and URL-only snapshots; no identity is inferred from a synthetic reference or a merely similar URL. A repeated source contributes once, using the latest **eligible** snapshot. Exclusions and duplicate counts are reported. A cohort needs at least five distinct comparable sources; five is only a research gate to flag tiny samples, not a confidence guarantee. The target and peer values remain visible in every eligible result.

| Method | Research result | Requirements and limits |
| --- | --- | --- |
| `account_median` | Target minus account cohort median, in original units | Descriptive difference; account identity and sufficient cohort required. |
| `baseline_ratio` | Target / cohort median | Median must exceed zero. No follower count is inferred. |
| `log_ratio` | Natural log of target / median | Both target and median must exceed zero. |
| `percentile` | Midrank percentile of target among peer values | Ties use half credit; the target is excluded. |
| `robust_deviation` | `(target - median) / (1.4826 × median absolute deviation)` | MAD must exceed zero; heavy ties can make it unavailable. |
| `age_matched_percentile` | Midrank percentile among peers within two days of target age | The age gate now applies to all peer methods, so this presently uses the same peers as `percentile`; retained as an explicit research diagnostic, not an independent signal. Two days is unvalidated. |

### AccountBaseline versus peer-video cohorts

The frozen `AccountBaseline` is a **precomputed summary of an explicitly described cohort**. It already requires a source, one semantic definition for every metric, positive sample size, timezone-aware ordered cohort window, nonblank cohort definition, and method reference. These fields are machine-readable and validated. The prior statement that the contract broadly "lacks machine-checkable context needed for safe comparison" was too broad. The narrower issue is that its `source`, `cohort_definition`, and `method_reference` are free-form strings; the baseline has no structured platform, exposure class, account ID, content type, provider-field qualification, per-video publication ages, observation-window basis, or verifiable target-exclusion flag. The baseline window describes cohort selection, **not** the metric observation window for every member. A valid baseline document alone therefore cannot establish those comparison dimensions or prove the summary's underlying membership and calculation.

The research-only `account_baseline` path keeps the attached `AccountBaseline` intact and accepts a separate structured `baseline_context` declaration. It requires matching platform, account ID, organic/paid exposure, snapshot source, content type, declared format, attribution context, and `publication_to_fetch` observation basis; a target age within a declared baseline age range; `target_excluded: true`; identical metric definitions; at least five baseline members; and `method_reference: "median"`. Known conflicts are ineligible. Missing fields, unknown exposure, invalid age ranges, or unverified target exclusion return insufficient evidence. When both format or attribution fields are null, the result states that comparability is unestablished. The code cannot validate whether external declarations are true or whether the baseline summary was deduplicated. Only median difference, ratio, and log ratio can use this summary; percentile and MAD require individual peer values. A baseline with an unfamiliar method reference is not silently treated as a median.

A **peer-video cohort** consists of individual validated `BenchmarkVideo` records and is appropriate when membership, distinct-source count, values, and each candidate's context can be inspected. It supports percentiles and robust deviation as well as median methods. An `AccountBaseline` is appropriate when an upstream process has already computed and documented a cohort summary but individual peer records are unavailable or unnecessary for the method. Neither representation replaces the other. Both remain research evidence rather than production scoring policy.

A two-video cohort, missing account identity, null metric, zero denominator, unknown exposure, incompatible context, or absent age window returns an ineligible result with a reason. Each result carries target platform/exposure, metric definition and observation window, comparison kind and identity, cohort/baseline context, method, sample size, inputs, exclusions where applicable, and limitations. No result is a universal quality or viral score.

Run locally from `backend` with `python -m intelligence.run_normalization fixture.json`. The JSON contains `videos` (BenchmarkVideo-compatible objects) and `requests`. A request defaults to `{"target": "source-reference", "metric": "views", "comparison": "peer_videos"}`. For a precomputed summary, use `"comparison": "account_baseline"` and supply `"baseline_context"` with the structured fields listed above. Output is a JSON array with method, metric, target context, comparison context/identity, inputs, normalized result, eligibility, reason, sample size and limitations. It performs no network calls. Tests use synthetic fixtures only.

## Outperformance interpretation

If creator A normally gets a median 10,000 views and one video gets 40,000, its ratio is 4. If creator B normally gets 2,000,000 and one gets 3,000,000, its ratio is 1.5. The first video has stronger relative outperformance while the second has far more absolute reach. Both facts should be shown together with provider field, account cohort, age, count and uncertainty. Neither result proves content quality, creative technique causation, or future performance. Promotion, distribution changes, collaborations and changing account scale can alter the baseline.

## Future external reference set

Capture source ID/URL and deduplication group; provider/API field definition and version; exposure and promotion status; creator/account ID and scale observed at a dated point; media type and format; publication and fetch timestamps; exact metric observation and attribution windows; raw values including nulls; geography, placement and objective where applicable; acquisition rights and provenance. Account baselines need the same field definitions and a disclosed cohort selection rule.

Disqualify samples with unknown or mixed paid exposure for organic cohorts, ambiguous provider semantics, missing window/age for age-matched analyses, unverifiable source identity, suspected reposts without grouping, or compromised metrics. Keep uncertain samples in a separate audit pool. Paid boosts can make an otherwise organic post's counts inseparable; ad-level counts should form separate cohorts. Large accounts have different distribution opportunities, so account-relative comparisons should preserve absolute counts and account scale rather than treating ratios as quality. Reposts and multiple snapshots of one source must not inflate sample size. A set of only top performers selects on the outcome and creates survivorship bias; sample ordinary, weak, and strong posts using a documented inclusion frame.

## V9 direction and open questions

Begin with a small licensed, provider-defined dataset covering complete creator posting histories over fixed periods. Validate provider definitions and revision history with primary documentation, mark paid contamination, deduplicate sources, and compare matched-age account-relative methods against held-out periods. Report sensitivity to cohort size, age tolerance, zeros, outliers, and account scale. Keep per-method outputs separate until reliability and utility are measured; make no production policy choice from these fixtures.

Open questions: What are the provider's exact current view/play and reach definitions? Can cumulative organic windows be established for each field? How can promotions of organic posts be detected? What minimum account history supports stable patterns? Should peer cohorts be account-only or include matched creators? How should unavailable follower histories be represented? What entity key groups edits, reposts and syndicated copies? Which target outcome would validate usefulness without mistaking distribution for content quality?
