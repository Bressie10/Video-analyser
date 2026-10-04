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

The offline code enforces exact platform, performance source, organic/paid exposure, content type, declared format, and full metric definition equality. It requires the same account ID for creator-relative work. `unknown` and `mixed` exposure is ineligible. This conservative gate does not claim that passing records are causally or statistically exchangeable.

## Candidate experiments

The harness excludes the target from its cohort and deduplicates by platform plus provider ID (or URL). A cohort needs at least five distinct comparable sources; five is only a research gate to flag tiny samples, not a confidence guarantee. The target and peer values remain visible in every eligible result.

| Method | Research result | Requirements and limits |
| --- | --- | --- |
| `account_median` | Target minus account cohort median, in original units | Descriptive difference; account identity and sufficient cohort required. |
| `baseline_ratio` | Target / cohort median | Median must exceed zero. No follower count is inferred. |
| `log_ratio` | Natural log of target / median | Both target and median must exceed zero. |
| `percentile` | Midrank percentile of target among peer values | Ties use half credit; the target is excluded. |
| `robust_deviation` | `(target - median) / (1.4826 × median absolute deviation)` | MAD must exceed zero; heavy ties can make it unavailable. |
| `age_matched_percentile` | Midrank percentile among peers within two days of target age | Only available when explicit snapshot window starts at publication and ends at fetch. Two days is an unvalidated experiment. |

The optional `AccountBaseline` contract contains a metric, method reference, cohort description and sample size, but lacks a machine-checkable provider, exposure, media format and age/window context. The harness therefore computes its baseline from validated peer videos and does not trust an arbitrary attached baseline for division. This is a contract limitation to resolve in a future adapter or documented cohort manifest, **not** a reason to alter the frozen schema here. A two-video cohort, missing account identity, null metric, zero denominator, unknown exposure, incompatible context, or absent age window returns an ineligible result with a reason. No result is a universal quality or viral score.

Run locally from `backend` with `python -m intelligence.run_normalization fixture.json`. The JSON contains `videos` (BenchmarkVideo-compatible objects) and `requests` (`{"target": "source-reference", "metric": "views"}`). Output is a JSON array with method, metric, context, target, cohort IDs, inputs, normalized result, eligibility, reason, sample size and limitations. It performs no network calls. Tests use synthetic fixtures only.

## Outperformance interpretation

If creator A normally gets a median 10,000 views and one video gets 40,000, its ratio is 4. If creator B normally gets 2,000,000 and one gets 3,000,000, its ratio is 1.5. The first video has stronger relative outperformance while the second has far more absolute reach. Both facts should be shown together with provider field, account cohort, age, count and uncertainty. Neither result proves content quality, creative technique causation, or future performance. Promotion, distribution changes, collaborations and changing account scale can alter the baseline.

## Future external reference set

Capture source ID/URL and deduplication group; provider/API field definition and version; exposure and promotion status; creator/account ID and scale observed at a dated point; media type and format; publication and fetch timestamps; exact metric observation and attribution windows; raw values including nulls; geography, placement and objective where applicable; acquisition rights and provenance. Account baselines need the same field definitions and a disclosed cohort selection rule.

Disqualify samples with unknown or mixed paid exposure for organic cohorts, ambiguous provider semantics, missing window/age for age-matched analyses, unverifiable source identity, suspected reposts without grouping, or compromised metrics. Keep uncertain samples in a separate audit pool. Paid boosts can make an otherwise organic post's counts inseparable; ad-level counts should form separate cohorts. Large accounts have different distribution opportunities, so account-relative comparisons should preserve absolute counts and account scale rather than treating ratios as quality. Reposts and multiple snapshots of one source must not inflate sample size. A set of only top performers selects on the outcome and creates survivorship bias; sample ordinary, weak, and strong posts using a documented inclusion frame.

## V9 direction and open questions

Begin with a small licensed, provider-defined dataset covering complete creator posting histories over fixed periods. Validate provider definitions and revision history with primary documentation, mark paid contamination, deduplicate sources, and compare matched-age account-relative methods against held-out periods. Report sensitivity to cohort size, age tolerance, zeros, outliers, and account scale. Keep per-method outputs separate until reliability and utility are measured; make no production policy choice from these fixtures.

Open questions: What are the provider's exact current view/play and reach definitions? Can cumulative organic windows be established for each field? How can promotions of organic posts be detected? What minimum account history supports stable patterns? Should peer cohorts be account-only or include matched creators? How should unavailable follower histories be represented? What entity key groups edits, reposts and syndicated copies? Which target outcome would validate usefulness without mistaking distribution for content quality?
