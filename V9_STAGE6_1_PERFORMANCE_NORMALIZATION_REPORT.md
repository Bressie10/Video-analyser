# V9 Stage 6.1 — Performance normalization research report

Base: `1dc11b6b23a40442e9602dae9c2b859ab45bde69`. Branch: `codex/v9-stage6-performance-normalization`.
Scope: offline `backend/intelligence/performance_comparison.py` and synthetic tests only. Schema version: `v9-stage6.1-1`.

## 1. Existing normalization behavior reused

`backend/intelligence/normalization.py` was audited, not copied. Stage 6.1 retains its minimum five **peer** records, target exclusion by exact provider ID/public URL including transitive aliases, deduplication after eligibility filtering, account median, ratio, log ratio, midrank percentile, median absolute deviation (MAD) scaled by 1.4826, and the ±2-day publication-age tolerance as an unvalidated research hypothesis. Zero median, zero target for log ratio, and zero MAD leave the affected method unavailable.

## 2. Behavior changed and why

- The old `BenchmarkVideo` snapshot cannot express Meta Ads reporting dates, account currency, action collection/type/window, or workspace identity. Stage 6.1 accepts explicit offline records that pair production-shaped `performance_source`/`performance_metrics` with those identity and observation fields. It does not change frozen benchmark schemas.
- The old module returns one row per normalization method and can use a declared baseline summary. Stage 6.1 returns one versioned report with separate per-metric records and auditable peers. It requires inspectable peer records; no baseline summary comparison is inferred.
- Organic counts require explicit publication and observation timestamps and the same declared content type and format. Missing format abstains rather than treating unknown format as comparable.
- Paid comparisons match reporting dates, Meta ad account, action report time, attribution-window configuration, and currency for monetary metrics. These dimensions were unavailable in the old benchmark contract.
- Every exclusion and unavailable calculation has a machine-readable reason. A context SHA-256 fingerprint hashes canonical, sorted JSON of cohort dimensions and the metric definition. It is a guard against silent aggregation across contexts, not a provider quality guarantee.

## 3. Organic cohort contract

Each record supplies `workspace_id`, `platform`, `performance_source`, `exposure_type`, `account_id`, `reference`, `provider_id` and/or `public_url`, `content_type`, `declared_format`, `published_at`, `observed_at`, `fetched_at`, and production-shaped `performance_metrics`. Source and platform must be the same one of Instagram, Facebook, or TikTok; exposure must be organic. Target and peers must match workspace, platform, source, account, content type, format, and metric definition. Publication age is observation time minus publication time; a peer is eligible only within ±2 days of the target. This controls one visible timing dimension but cannot establish equal distribution or reach. Counts remain age/exposure dependent.

## 4. Meta Ads cohort contract

Paid records use source `meta_ads`, paid exposure, an explicit Facebook or Instagram platform, Meta ad account in `account_id`, and `performance_metrics.meta_ads` from the production shape. Target and peers match workspace, platform, source, account, `date_start`, `date_stop`, `action_report_time`, and the ordered `action_attribution_windows` configuration. Monetary metrics additionally match `account_currency`. Action metric IDs encode collection, action type, and selected window; these are never pooled. Equal reporting periods do not imply equal spend or delivery opportunity.

## 5. Supported raw metrics

Organic: `view_count`, `like_count`, `comment_count`, `share_count` as separate provider-specific counts. Paid: `impressions`, `reach`, `clicks`, `spend`, provider-reported `ctr`, provider-reported `cpc`, and `action:<collection>:<type>:<window>` where collection is `actions`, `conversions`, or `video_play_actions`, and window is `7d_click` or `1d_view`. The registry contains description, unit, source, exposure, raw/derived status, formula, required inputs, descriptive direction, and limitations. The comparison context includes that definition, so unlike provider definitions cannot share a fingerprint.

## 6. Supported derived metrics

`cpm = spend / impressions * 1000` requires a currency and positive impressions. `frequency = impressions / reach` requires positive reach. `derived_click_rate = clicks / impressions * 100` requires positive impressions and remains distinct from reported `ctr`. `cost_per_action:<collection>:<type>:<window> = spend / selected attributed action count` requires currency, spend, and a positive count for exactly that collection/type/window. Missing inputs and zero denominators abstain. No ROAS is calculated because revenue/value semantics are not established by this contract.

## 7. Normalization methods

For each metric independently: peer median, target minus median, target/median, natural log of that ratio, peer midrank percentile, MAD, and `(target − median) / (1.4826 × MAD)`. The organic percentile is also identified as an age-matched percentile because all eligible peers satisfy the age rule. Decimal inputs and division preserve decimal precision; log ratio and percentile use floating point. Each metric record carries target and peer values, raw/derived provenance, formula inputs, sample size, eligibility, abstentions, and context fingerprint. Output ordering is deterministic across candidate input order.

## 8. Abstention rules

Unknown target context/value, absent or null metric, missing action type/window value, currency, publication or observation time, or fewer than five eligible distinct peers blocks the metric comparison. Candidate mismatches and duplicate aliases have explicit reason codes. Median zero blocks ratio and log ratio; target zero blocks log ratio; MAD zero blocks robust deviation. These method abstentions do not erase mathematically valid median/delta/percentile outputs. The target and exact identity aliases are excluded before peer deduplication, with an explicit exclusion proof.

## 9. Synthetic fixture results

Organic target 40 versus peers `[5, 10, 10, 15, 20]` gives median 10, delta 30, ratio 4, percentile 100, MAD 5, and robust deviation `30 / (1.4826 × 5)`. The paid target has 1,000 impressions, 500 reach, 20 clicks, EUR 10 spend, and 2 attributed purchases in `conversions:purchase:7d_click`: CPM 10 EUR, frequency 2, derived click rate 2%, and cost per selected attributed purchase 5 EUR. Tests exercise account/platform/family/currency/date/attribution/action mismatches, target aliases, duplicate peers, missing/null values, zero denominators, zero median/MAD, insufficient peers, missing publication time, and age mismatch. No Stage 5 pilot truth is used.

## 10. Limitations and next gate

The offline caller must supply trustworthy workspace, provider object identity, account identity, platform, and timestamps from owned historical records. The normalized production snapshot alone does not supply all these fields, and this stage contains no production join or API. The current Meta Ads contract fixes `action_report_time=impression` and requests `7d_click` and `1d_view`; other contexts must be explicitly supplied and matched before comparison. Exact identity deduplication cannot detect undocumented aliases. Five peers and ±2 days are research thresholds, not confidence or provider equivalence claims. Comparisons are observational: no causal inference occurs, no semantic technique is involved, no provider equivalence is assumed, and no overall performance score exists. No LLM is called.

**A — comparison foundation is ready for testing against real owned historical performance.**
