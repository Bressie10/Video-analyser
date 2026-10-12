# V9 Stage 7.3 — Evidence-Backed Creative Hypotheses

## Scope and chosen architecture

Exact base: `fcefb313d5754c84fe6af061931023e89be430a1`. This is offline intelligence in one new module. It does not alter endpoints, ideas, frontend, storage, migrations, or experiment scheduling. The chosen path is **one structured `gpt-6-sol` call per eligible reasoning run**, with deterministic input selection, evidence copying, ranking, and rejection. No eligible difference means zero calls. An invalid model draft raises an error; it is not silently rewritten. The deterministic template remains available as the measured baseline.

Recommendations are hypotheses, not causal findings. No overall performance score exists. Each recommendation derives from one Stage 7.2 observed difference. The selected performance metric remains Stage 6-defined and only one metric lens enters a run.

## Deterministic baseline and LLM comparison

The baseline selects at most three actionable differences and inserts each into a generic test template. It reliably preserves source counts and refs at effectively zero runtime cost, but its control ("keep the observed condition") and variant ("change the variable") are too vague for a creator to execute. It cannot consistently specify an isolated change such as moving the **same** spoken offer from later in the video to the opening.

The one-call path sees only the selected Stage 7.2 differences, Stage 7.1 bounded fact for that metric, Stage 6 metric definition/context, counts, counterexamples, evidence refs, gaps, and coverage confidence. It never receives raw Stage 5 labels, motion, company profile, old recommendations, or other metric comparisons. In live synthetic probes the model produced concrete control/variant pairs, including a same-offer timing change and a product visibility opening change. That is a material usefulness gain over the template. It did not require another model pass, embeddings, or persistence.

## Evidence-to-hypothesis rules

- Stage 6 validation checks the metric definition and context fingerprint; Stage 7.2 must refer to the same metric and six distinct grouped videos.
- Every cited ref must exist in the Stage 7.2 input ledger and belong to a grouped video. The source support counts must equal the distinct cited videos in each group. The model chooses source indices; code copies descriptions, counts, counterexamples, refs, coverage, metric, and comparison context. The model cannot edit them.
- Only concrete visual, OCR, or spoken variables pass the small controllability gate. Product visibility requires frame evidence; visible text requires OCR; spoken content requires transcript evidence. Vague qualities, scene boundaries alone, missing refs, and low-coverage differences abstain.
- Priority is `strong_candidate`, `candidate`, or `weak_candidate`, based on Stage 7.2 support, timing, coverage, and counterexamples. It ranks what to test first, not a causal probability or numerical confidence score. At most three hypotheses are returned.

## Experiment design and counterexamples

Each item names one variable, control, variant, primary metric, comparison context, practical hold-constant list, source observation, support, counterevidence, refs, and limitations. Paid comparisons keep offer, core copy, CTA, objective, audience, placement scope, attribution settings, and reporting window as similar as practical. Perfect platform control is not assumed. No sample size, duration, power, significance threshold, or delivery sufficiency threshold is invented.

The 3/3 versus 1/3 fixture keeps the lower-group citation and count. The final item adds an explicit limitation that the feature also appeared on the other side. A timing difference supported in both groups is ranked by its checked temporal relation, not by prevalence count alone. Lower CPC remains a cost lens; it is never relabeled as a general creative success metric.

## Causal and factual guard

Model-authored text must remain explicitly uncertain and name a concrete variable. The validator rejects causal verbs and equivalent established-effect language, digits that could smuggle unsupported numbers, unrelated CTR/CPC/CPM terms, identical control and variant, unknown source indices, duplicated sources, and more than three hypotheses. The prompt treats source text as data, not instructions. Source facts are copied from checked input rather than regenerated. A validator cannot prove that a Stage 7.2 visual interpretation itself is correct, nor can it prove full creative isolation from prose alone; cited frames and the proposed edit still need human review before product use.

## Evaluation results

Twelve deliberately synthetic scenarios were used. The clean visual fixture uses synthetic frame citations; it is a grounding-contract test, not a visual-accuracy benchmark. The final one-call matrix made eight live calls; four cases abstained or rejected before any call. All eight final drafts passed validation. An earlier exploratory timing draft failed the uncertain-language check; a narrow prompt clarification preceded the final matrix. No accepted draft changed a source count, source ref, metric, or counterexample. The causal-instruction attempt in an evidence gap did not produce a causal claim. The missing-ref case rejected before the API call.

| Scenario | Deterministic baseline | Live one-call result |
| --- | --- | --- |
| 3/3 vs 0/3 actionable opening | Generic test | Concrete control and opening variant |
| 3/3 vs 1/3 counterexample | Generic test, counterexample retained | Concrete design, counterexample retained |
| 2/3 vs 0/3 | Generic test | Concrete design |
| Weak 2/3 vs 1/3 | Abstained | Abstained without call |
| Non-actionable visual quality | Abstained | Abstained without call |
| Vague model feature | Abstained | Abstained without call |
| Checked spoken timing | Generic test | Same-offer timing test accepted |
| Lower-CPC lens | Generic test | Concrete design retaining CPC |
| Two competing variables | Two generic tests | Two distinct concrete tests |
| Four possible variables | Top three generic tests | Three distinct concrete tests |
| Causal instruction attempt | Generic test | Uncertain test; instruction ignored |
| Missing evidence ref | Rejected | Rejected before call |

Grounding failures and accepted causal violations in the final synthetic set: zero. Invalid experiment designs among accepted model outputs: zero on manual review of the returned control/variant pairs. The earlier rejected timing draft shows that fail-closed language validation can reduce availability. These are small synthetic checks, not population reliability or semantic accuracy estimates.

## Cost and runtime

The baseline took less than one millisecond per synthetic case. The eight final live calls took about 25.1 seconds total, about 3.1 seconds per call. Recorded usage was 9,276 input and 1,321 output tokens. At [official `gpt-6-sol` standard rates](https://developers.openai.com/api/docs/models/gpt-6-sol) of $2 per million input tokens and $10 per million output tokens, the approximate final-matrix API cost was $0.032, assuming uncached standard input pricing. Earlier exploratory and targeted calls were additional evaluation cost. Runtime cost is one model call per eligible comparison; production cohorts may have different prompt sizes.

## Validation and limitations

- Stage 6, Stage 7.1, Stage 7.2, Stage 7.3 focused discovery: 122 passed.
- Recommendation API regression: 14 passed. Motion downstream gate: 3 passed.
- Backend non-DB discovery, excluding the DB-only V6 integration module: 570 tests, zero failures, 284 environment/DB-dependent skips. An unfiltered discovery first exposed eight V6 integration errors because `TEST_DATABASE_URL` was absent; that suite was outside this offline scope.
- Python compilation, changed-file privacy scan, and `git diff --check`: passed.

No production API, real Meta cohort, real source-video semantic review, database integration, frontend, or live experiment was tested. Sparse sampled frames cannot prove continuous absence. The model's useful experiment prose is still bounded by the quality of Stage 7.2's provisional observations and the comparability of actual delivery.

A — hypotheses are grounded and actionable enough for product integration
