# V9 Stage 7.2 — Cross-Video Content Difference Reasoning

## Scope and decision

- Exact base: `f95a4cf6e0508a53af3d1939c059317e981bb557`.
- Implementation commit: `c909fed` on `codex/v9-stage7-cross-video-content` (the report is committed separately).
- Chosen design: **one structured OpenAI call per offline comparison**. A batched blind description pass followed by a comparison pass was tested and removed from the implementation because it did not materially improve accepted evidence quality on this deliberately small synthetic set.
- Production files changed: `backend/intelligence/cross_video_content.py` only. The other additions are `backend/tests/test_stage7_2_cross_video_content.py` and this report. No frontend, route, recommendation, idea generation, persistence, migration, or background-job changes.

## Evidence and grouping contract

The caller supplies a validated Stage 6 `PerformanceComparisonReport`, one metric ID, and raw content for the selected provider objects. `construct_groups` checks the Stage 6 metric definition and Stage 7.1 evidence summary, rejects unresolved older versions or duplicate provider IDs, and requires at least six distinct objects in one exact context. It selects the three highest and three lowest **numeric values**; middle objects are excluded. A tie crossing either cutoff causes abstention. The output retains each selected provider identity, opaque video reference, exact metric value, available percentile, and context fingerprint. For CPC and other lower-cost metrics, “lower” means numerically lower cost, not universal creative quality.

Only transcript segments, consolidated OCR, scene boundaries, duration, and bounded deterministic JPEG samples from source media enter content reasoning. Up to 24 transcript segments, 24 OCR entries, 12 scenes, and six frames per video are sampled; sampling gaps are reported. The frame-selection/extraction functions are pure deterministic utilities reused from the existing evaluation package. No Stage 5 semantic candidate, label, structure role, CTA classification, or truth is read. Neither motion nor company/profile/recommendation/idea output enters the payload. A private pilot source was decoded in a frame-only smoke check (six sampled timestamps); it was not given invented performance labels.

The one-pass model receives six raw evidence packets, only the selected higher/lower metric group references, and the bounded Stage 7.1 fact for that metric. It uses the project's `gpt-6-sol` Responses structured-output convention with reasoning effort `none` and `store=False`. The report records model, prompt SHA-256, response ID when available, input evidence references, token usage, latency, and the executing code commit. Media bytes and raw model responses are not committed.

## Pattern, counterexample, and temporal rules

The model proposes literal features and exact citations. Code checks every citation against the supplied raw evidence and group membership. A feature needs at least two of three videos on one side **and** a different count on the opposite side. One-video examples and 2/3 versus 2/3 claims become mixed/inconclusive. Missing frame or OCR coverage on any selected video demotes a claim based on that modality. Minority-group examples and contrasting content are retained as counterexamples. Similarities require at least two cited videos in each group.

Temporal claims require the same feature to be cited in at least two videos in **each** group. The code compares median cited timestamps and requires a gap of at least one second. A fixed-time sampled-frame presence claim is a prevalence observation, not an “earlier” claim. Confidence describes citation coverage only (`high`, `medium`, `low`); it is not causal or statistical confidence. Sparse frames cannot establish continuous visual absence.

The language guard rejects causal verbs and generic advice in accepted model text. The prompt also bars causes, effectiveness judgments, outside benchmarks, and unsupported marketing knowledge. A rejected result raises an error rather than returning a claim. The validator proves citation existence, group counts, coverage, and timestamp arithmetic; it cannot prove that a model's visual interpretation is semantically correct, so human review of referenced frames remains necessary.

## Synthetic one-pass versus blind two-pass experiment

Both designs used the same 11 synthetic contexts, `gpt-6-sol`, structured output, and exact validator. The blind design used **one batched pass for six unlabeled content packets**, then one group comparison call. All provider IDs, metric values, text, and test images were synthetic. The visual cases used generated JPEGs; public Ad Library content was not used as performance truth.

| Scenario | One pass | Blind two pass |
| --- | --- | --- |
| 3/3 versus 0/3 repeated transcript difference | Accepted with citations | Accepted with citations |
| One-video-only difference | No group pattern | No group pattern |
| 2/3 versus 0/3 | Accepted | Accepted |
| 2/3 versus 2/3 | No group pattern | No group pattern |
| 3/3 versus 1/3 counterexample | Accepted, counterexample retained | Accepted, counterexample retained |
| Same words at 2s versus 8s | Timestamped transcript and OCR differences | Same two differences |
| Sampled opening frames | Initially demoted by ambiguous temporal flag; accepted after targeted prompt/guard correction | Same outcome after correction |
| One missing opening frame | Demoted for coverage | Demoted for coverage |
| CPC lens with reversed numeric order | Correct higher/lower-cost grouping and one content difference | Correct grouping, but duplicated the complementary difference |
| One missing OCR stream | Demoted for coverage | Demoted for coverage |
| Untrusted transcript instruction containing a causal claim | No accepted claim or instruction following | Blind description echoed forbidden wording and was rejected |

Across the initial 11-case matrix, accepted unsupported claims, accepted wrong references, and false group patterns were **zero for both designs** under the validator and manual review. Both initially missed the obvious visual difference because they selected a temporal flag for a fixed-time presence claim. A focused rerun after clarifying the prompt and permitting “first sampled” wording accepted the 3/3 versus 0/3 frame pattern in both designs. One pass handled the counterexample and the timing difference as well as two pass. The blind design gave no measurable confirmation-bias reduction here, while its extra description step introduced one causal-language rejection on the untrusted-text case. These are small-fixture findings, not a population accuracy estimate.

| Measured initial matrix (11 cases) | One pass | Blind two pass |
| --- | ---: | ---: |
| Model calls completed | 11 | 21 (final case rejected after pass 1) |
| Mean wall time per case | 6.73 s | 13.02 s |
| Input / output tokens | 21,790 / 6,890 | 35,373 / 14,687 |
| Approximate total API cost | $0.112 | $0.218 |
| Approximate cost per case | $0.010 | $0.020 |

Cost estimates use the [official GPT-6 Sol standard API rates](https://developers.openai.com/api/docs/models/gpt-6-sol) of $2 per million input and $10 per million output tokens, assuming all input is billed uncached; actual billing can differ with cached tokens or service tier. The targeted visual rerun was extra evaluation work and is excluded from the matrix totals. The simpler one-call path is therefore the committed runtime design.

## Regression and privacy checks

- Stage 6.1, 6.2, 7.1, 7.2, observation unit/API, recommendation, and motion-gate focused suite: **49 passed**.
- Backend non-DB discovery (excluding the DB-only V6 integration module): **566 discovered, 284 environment/DB-dependent skips, zero failures**. The first unconfigured attempt failed on missing test-only `jwt` and `TEST_DATABASE_URL`; rerun with the existing test dependency path passed.
- Real local disposable PostgreSQL `v9_stage64_disposable_20261012` via `TEST_DATABASE_URL` only: **six Stage 6 performance, observation, and Meta DB tests passed**. The first sandboxed attempt could not open loopback TCP; the approved rerun passed. No production DB was used.
- Stage 7.2 contract tests: **nine passed**. Python compilation and `git diff --check` passed.
- Privacy scan of the changed files found only explicitly synthetic fixture identities. No access token, real provider/account ID, customer metric, name, source media, or raw model response was committed.

## Limits and next step

This is an offline contract and small synthetic model experiment. No live Meta performance plus private source-media cohort was available, so real-world content-difference usefulness and model visual accuracy remain unverified. The one-pass model can still be influenced by group labels; exact citations and support checks constrain but do not eliminate confirmation bias. Report consumers must retain the Stage 6 context, selected metric, gaps, and counterexamples. Reports are not persisted or exposed through an API.

Stage 5 semantic labels were not used. Motion was not used. No causal inference was made. Performance grouping came only from Stage 6/7.1 facts. Public Ad Library content was not treated as performance truth. There is no overall content or performance score.

A — cross-video content differences are grounded and useful enough to proceed
