# V9 Stage 8.1 — Product Intelligence Integration

Base: `5f0a97ef6e130d6b40570385e8484be84f838a9b` on `v9`. Branch: `codex/v9-stage8-intelligence-integration`. Backend only; no migration, cache, queue, frontend change, deploy, or tag.

## Actual production data path

| Required fact | Production state | Integration path |
| --- | --- | --- |
| Company authorization | Already available | `authorize` checks membership before account or observation reads. |
| Provider ad ID and Meta ad account ID | Already available | Assigned `meta_library_items` and linked `meta_accounts`; immutable observation repeats both IDs. |
| Latest comparable performance observation | Available but not exposed to this product flow | Stage 6 repository reads exact date, placement, account, attribution, report time, and currency. Adapter collapses versions per provider object. |
| Ad to ContentMetric video association | Available but not exposed to this flow | Explicit `meta_ad_assets` edge leads to one analyzed video asset; ambiguous/missing assets abstain. |
| Transcript, OCR, and scenes | Available but not exposed to this flow | `read_analysis` loads ordered children. Empty transcript/OCR become explicit Stage 7.2 evidence gaps; scene data is required. |
| Source video bytes | Unavailable after analysis | Worker deletes temporary download. Stage 8.1 re-resolves the authorized asset's Meta video ID and downloads source to a bounded temporary file for frame sampling. The file is removed after packet preparation. |

The media bridge reuses `meta_media.media_url` and `download`, including their provider identity, URL, size, redirect, and time limits. It never treats the ad ID as a video ID or stores the media. An asset whose provider media is no longer accessible yields performance-only intelligence.

## Endpoint and orchestration

`POST /api/companies/{company_id}/intelligence` accepts only `account_id` (linked Meta account UUID), `metric_id` (`ctr`, `cpc`, `cpm`, `impressions`), `date_start`, and `date_stop`. Invalid dates/metrics return 422; foreign company/account returns 403/404. Disconnected Meta and expected evidence gaps return HTTP 200 with structured abstentions. Response is private and uncached.

`company_intelligence.py` validates company/account ownership, finds the one exact report context, reads current assigned observations, keeps the latest version of each ad, and requires five Stage 6 peers. Stage 6 comparison and deterministic Stage 7.1 reasoning are unchanged. It selects Stage 7.2 higher/lower groups, checks six unique analyzed video assets, downloads their source bytes, then uses Stage 7.2's one-call packet and validator. Only actionable validated differences enter Stage 7.3's one-call validator. The response contains bounded metric facts (peer count, ratio, percentile, limitations), group-to-provider references, differences and citations, up to three hypotheses, abstentions, limitations, and sanitized model usage/latency provenance. No prompt or raw model payload is returned.

Insufficient cohorts abstain without performance claims. Missing or ambiguous video association, incomplete analysis, unavailable media, or failed frame decoding preserves Stage 7.1 performance and uses zero LLM calls. Stage 7.2 rejection/model failure preserves performance; Stage 7.3 rejection/model failure preserves validated differences. The full path uses at most two model calls. No hypothesis is presented as a causal effect.

## Validation

- Disposable PostgreSQL, actual migrations, HTTP API, synthetic assigned observations, asset analyses, mocked media, and mocked model: Stage 8.1 focused tests pass (4). Cases cover full DB-to-API success, latest-version deduplication, performance-only degradation with zero model calls, insufficient cohort, unauthorized company, foreign account, unsupported metric, disconnected Meta, unavailable media, Stage 7.2 validator rejection, Stage 7.3 validator rejection, and model timeout.
- Stage 6 and Stage 7.1–7.3 focused suites pass. Complete backend suite: **582 tests, 0 failures, 3 skips**. The skips require local OCR/Whisper models and `RUN_MEDIA_INTEGRATION=1`; the mocked Stage 8.1 source-media path ran.
- Python compilation and `git diff --check` pass. No frontend path or migration changed. Privacy scan found no committed credential or source-media artifact in the changed files.

## Security, cost, and remaining limits

The caller cannot supply provider IDs, cohort members, values, analyses, citations, or model evidence. The service rechecks company membership and current ad assignment before reading asset evidence. It requires one linked Meta account and exact report context. The temporary media bridge inherits existing bounded download and source URL checks. Tests use synthetic IDs; no live account data was committed.

Stage 7.1 costs zero model calls; a complete result costs one Stage 7.2 call and at most one Stage 7.3 call. A six-video comparison may download up to six source files of at most 500 MiB each and sample at most six frames per video. The mocked test runtime is not a live latency or token-cost measurement. Sequential provider download and model latency should be measured during live validation before deciding whether a queue or cache is needed.

Live Meta validation is pending. Manual path: (1) connect an owned Meta account, (2) collect at least six assigned ad observations for one exact reporting window and context, (3) ensure the six selected creative assets are analyzed and currently downloadable, (4) invoke the endpoint for CTR, and (5) inspect every returned evidence reference against the corresponding source video. Do not treat local/mock validation as provider or production proof.

Remaining product work: Stage 8.2 UI and a real-account trial; no storage redesign or persistence is justified by current measurements.

A — backend intelligence flow is ready for UI/live validation
