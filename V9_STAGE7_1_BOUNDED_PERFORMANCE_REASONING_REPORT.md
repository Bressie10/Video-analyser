# V9 Stage 7.1 — Bounded Performance Reasoning

## Scope and architecture

- Exact base: `54f2922d04fcd373ed5ada0deeedbe5e744d4352` on `v9`.
- Branch: `codex/v9-stage7-performance-reasoning`. Audited code head: `5fc3354e6d935adfdffef85ce4579d3c7fb0e5a5`; this report is a later documentation-only commit.
- Offline only: one `backend/intelligence/performance_reasoning.py` module and one synthetic test module. No frontend, database, migration, route, recommendation, idea-generation, or Stage 5 integration changed.

The chosen path is `PerformanceComparisonReport → PerformanceEvidenceSummary → deterministic PerformanceReasoningResult`. Plain dictionaries keep the contract small. The summary accepts the Stage 6.1 report version and metric registry, then copies only approved comparison facts. It rejects a mismatched metric definition, non-finite values, an ineligible cohort passed as eligible, or a malformed fingerprint. Disallowed input fields such as transcripts, motion, semantic labels, profiles, and previous reasoning are not copied.

## Evidence, salience, and language

For each eligible metric, the summary retains its ID, description, direction semantics, exact target and median values, available ratio, percentile, available robust deviation, peer count, context fingerprint, raw/derived status, method abstentions, exclusion count, and metric limitations. Ineligible metrics retain only their IDs and abstention reasons. The renderer returns a short summary, notable metrics with traceable numbers, mixed signals, abstentions, limitations, and evidence references.

The documented research salience thresholds are percentile ≥80 or ≤20, ratio ≥1.25 or ≤0.80, or absolute robust deviation ≥1. They govern presentation only; none is a statistical significance threshold. The renderer states above/below/near relative to the cohort median. It preserves Stage 6 direction semantics: spend and delivery are quantities, not automatically better outcomes; CPC and CPM describe cost; frequency is exposure repetition. A five-peer cohort is named explicitly and carries a limited-percentile-resolution warning. Numeric percentile and ratio fields remain exact Stage 6 values, but prose does not claim account-wide rank or scientific precision.

The renderer explicitly surfaces high CTR with high CPC, high impressions with low CTR, opposing provider/derived click rates, and more attributed actions with higher cost per action. It does not combine these into a score. When a requested metric abstains, no value is inferred. A language guard rejects causal verbs and phrases, including “caused,” “drove,” “because,” and “proves”; the deterministic templates use observational wording. This guard is intentionally stricter than allowing negated variants.

## Fixture evaluation and model decision

Fourteen compact paid scenarios cover strong/weak click response, CTR/CPC conflict, low CPM with average CTR, high spend with average click efficiency, actions/cost conflict, near-baseline metrics, one and several abstentions, five and nine peers, zero MAD, higher delivery with weak CTR, and provider-versus-derived click-rate conflict. A separate zero-median case confirms ratio abstention; an organic case confirms descriptive count language. Expected checks assert the facts and conflicts that must appear, not exact prose. Tests also reject malformed Stage 6 facts, strip forbidden upstream fields, and exercise the causal-language guard. All passed.

The deterministic rendering covered the fixture requirements with concise, traceable wording. No LLM variant was run: there was no observed prioritization, conflict, readability, or conciseness failure needing a model call, and external model work was not necessary for this stage. An LLM is therefore **not justified** on the current evidence. This is a decision from the deterministic fixture results, not a claim that an LLM could never improve later writing. Runtime is local and has no API cost; one local run rendered a three-metric report 10,000 times in about 0.2 seconds. A one-call LLM path would add provider latency, monetary cost, and factual/causal validation work without a measured gain here.

## Regression, privacy, and limits

- Stage 6.1/6.2/6.3, new Stage 7.1, recommendation, and motion-gate focused tests: 38 passed, zero failures/skips. The final non-DB run repeated these after the presentation-order edit.
- Stage 6 DB observation, Meta Ads, and existing performance tests against the explicitly disposable local PostgreSQL database via `TEST_DATABASE_URL`: six passed, zero failures/skips. No production database was used.
- Backend non-DB suite: 263 tests across 39 modules, zero failures, two existing media-model skips.
- Python compilation, privacy scan, and `git diff --check`: passed. The scan found no long provider identifiers or token patterns in added files and no disallowed product imports in the reasoning module.

These are synthetic, hand-chosen cases; they do not establish usefulness with real users or live Meta behavior. Percentiles are especially coarse at five peers, metrics sharing inputs are not independent evidence, and Stage 6 cohort selection and exclusions continue to define what any sentence can mean. There was no live provider test or model comparison. No semantic creative techniques were used, no causal inference was made, and no overall performance score exists. Reasoning remains bounded by the Stage 6 cohort.

A — bounded performance reasoning is useful and ready for cross-video content reasoning
