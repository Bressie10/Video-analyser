# V9 Stage 5.4 — format semantics and atomic structure

**Decision: B — stop prompt tuning and obtain independent review.** The two
architecture changes work on this four-video pilot: localized evidence can
support a whole-video format, and the accepted primary structure timeline has
no incompatible overlaps. The candidate is auditable, but disagreements with
the AI-assisted, non-blind Stage 5.1 truth remain, and aggregate label and
structure agreement did not retain all Stage 5.3 gains. Do not run the other
seven videos automatically.

## Scope and provenance

- Exact base: `a124fdcf657372f791e21d5b9c26f837311fbeae`.
- Branch: `codex/v9-stage5-4-semantic-consistency`; isolated worktree.
- Sources: `01 04 08 12` only. No reviewed truth, performance, or motion was
  supplied to either inference pass. Comparison ran after all four candidate
  files existed.
- Requested and reported model: `gpt-6-sol` for every call. Final Pass 1 prompt
  SHA-256: `b6b6e28ddc272a547dd71e04bb587e58926cb0d420e0c7bc52b1bbed73dd57ce`.
  Pass 2 prompt SHA-256:
  `117850c2e1705d0fbb58c08a438cef7e1022c7054ed04f6f8ceeca402428dd27`.
  Each [candidate](backend/intelligence/evaluation/stage5_4/candidates/) records
  every response ID, requested/reported model, prompt hash, generating analyzer
  commit, and later validation commit. The validated candidates used
  `df46317aa3a184ce81941941ea76ed6d4ca6e274` for final validation; per-pass
  records identify the actual commit used for each model response. Frozen
  ontology `1.1.0` and report schema `2.0.0` were unchanged.
- Original Stage 5–5.3 artifacts were left unchanged. The comparison and all
  new inference artifacts are under
  [stage5_4](backend/intelligence/evaluation/stage5_4/).

## Architecture result

Pass 1 now returns atomic observations with a reason for each boundary. A
boundary reason has to cite evidence of the matching source type; visible
actions require frame citations. Observations cannot extend past the time
envelope of their substantive frame, transcript, or OCR references. When a
model supplies broader times, the derived ledger clamps them and records the
original interval. The four videos produced 14, 40, 22, and 9 ledger items,
respectively; 1, 6, 2, and 1 items had recorded edge clamps.

Pass 2 assesses every whole-video format against its literal frozen definition,
with a decision, positive ledger references, limitations, and criterion
explanation. A supported format can use a localized segment where the
definition allows it. CTA labels remain grouped by physical event. Candidate
intervals are limited to cited atomic evidence, including contiguous event
evidence for labels on the same CTA. Four unsupported synthesis edges in `08`
were trimmed and recorded. Internal evidence gaps and incompatible primary
structure overlaps still reject candidate acceptance. No `other` role was
inserted to fill gaps. The final structure timelines have **zero incompatible
overlap pairs** on all four videos. All four independent ledger-support audits
returned **zero failures**.

## Comparison with provisional Stage 5.1 truth

Micro scores over the four videos, restricted to complete reviewed categories;
partial and unavailable categories abstain. Interval columns show F1 at the
specified boundary tolerance. Structure agreement is scored only where Stage
5.1 structure coverage permits it. These are agreement scores, not validated
population accuracy.

| Candidate | Label P / R / F1 | Interval F1 ±0.25 / ±0.5 / ±1.0 | Structure P / R / F1 | Incompatible overlaps |
| --- | --- | --- | --- | --- |
| Stage 5.2 | .833 / .938 / .882 | .412 / .647 / .765 | .636 / 1.000 / .778 | 0 |
| Stage 5.3 | .789 / .938 / .857 | .286 / .457 / .514 | .875 / 1.000 / .933 | 2, both in `12` |
| Stage 5.4 | .737 / .875 / .800 | .400 / .629 / .743 | .700 / 1.000 / .824 | **0** |

| Video | Stage 5.2 label TP/FP/FN | Stage 5.3 | Stage 5.4 | Stage 5.4 missed reviewed finding | Stage 5.4 findings unsupported by provisional truth |
| --- | --- | --- | --- | --- | --- |
| `01` | 4/2/0 | 3/2/1 | 3/1/1 | `format.talking_head` | `cta.visual` |
| `04` | 3/1/1 | 4/2/0 | 3/3/1 | `hook.visual` | `hook.curiosity_gap`, first `cta.visual`, `format.product_demo` |
| `08` | 5/0/0 | 5/0/0 | 5/0/0 | None | None; both `cta.product` labels fall in provisional uncertain coverage |
| `12` | 3/0/0 | 3/0/0 | 3/1/0 | None | `format.listicle` |

The exact matches, interval scores, reviewed items, candidate findings,
structure-role scores, CTA grouping, response provenance, edge adjustments,
and ledger failures are in
[side_by_side.json](backend/intelligence/evaluation/stage5_4/side_by_side.json).

## Format criterion evidence

| Video | Decision | Frozen criterion and cited evidence | Limitation or disagreement |
| --- | --- | --- | --- |
| `01` | `format.product_demo` supported | “Shows a product or service in use.” `ledger:0:2` shows the fragrance bottle near the speaker's nose while smell is discussed. Local use suffices. | The exact inhalation between sparse frames is unverified. `format.talking_head` is uncertain because camera-addressing speech over a substantial portion was not established to the model's confidence; provisional truth marks it present. |
| `04` | `format.before_after` supported | “Compares a state before and after a change.” `ledger:0:0`, `ledger:2:2`, and `ledger:3:1` show the earlier seated man and later groomed/clothed state. | `format.product_demo` is also supported from clipper use at `ledger:0:6` and `ledger:1:1`, which provisional truth did not list. This fits the literal ontology and needs independent review. |
| `08` | `format.product_demo` supported | Opening ledger items `ledger:0:0`–`ledger:0:6` show localized skincare product/tool use. | `format.screen_recording` is uncertain; the end card alone does not establish a principal screen recording. |
| `12` | `format.talking_head` supported; `format.listicle` supported | Repeated speaker-to-camera ledger items support the former; `ledger:1:1` and `ledger:1:2` enumerate course specialties, potentially satisfying “Presents numbered or clearly enumerated items.” | Whether the specialties are a format-defining enumeration or just a list within a sales explanation is unresolved by provisional truth. |

All other format assessments, including counterevidence and limitations, are
recorded verbatim from the model in the four candidate JSON files.

## CTA events and attached labels

| Video | Physical event and interval | Attached labels |
| --- | --- | --- |
| `01` | `cta:1`, 25.68–28.40s: grab/buy the fragrance | `cta.verbal`, `cta.visual`, `cta.product` |
| `04` | `cta:1`, 132.16–133.16s: help wear/spread love | `cta.verbal`, `cta.visual` |
| `04` | `cta:2`, 136.16–138.50s: join movement/buy yours | `cta.verbal`, `cta.visual`, `cta.product` |
| `08` | `cta:quiz_overlay`, 0–23.233s: tap for quiz/guide | `cta.visual`, `cta.product` |
| `08` | `cta:quiz_end_card`, 24.50–27.467s: take quiz | `cta.visual`, `cta.product` |
| `12` | `cta:1`, 32.16–35.44s: request course catalog | `cta.verbal`, `cta.product` |

The visible `01` caption says “grab yours,” so its `cta.visual` label fits the
frozen visible-request definition even though provisional truth did not include
it. `04`'s first closing caption contains “help me wear love,” a visible
request that may likewise fit. The two `08` quiz events clearly fit
`cta.visual`; whether a quiz/guide counts as a product-related action remains
uncertain in Stage 5.1. No CTA label was removed merely to match that truth.

## Requested questions and stop decision

1. **`01` product demo:** Yes, from localized fragrance-use evidence under the
   literal ontology definition. Its talking-head decision remains uncertain.
2. **`04` before/after and later sequence:** Yes. The candidate retains early
   before and later groomed state, then later leg-care demonstrations, a
   127–132s payoff, two distinct closing CTA events, and the meals claim
   between them. It leaves unsupported gaps.
3. **`08` end-card headline:** Yes, `text.headline` at 23.5–27.467s.
4. **`12` primary structure overlaps:** Zero. The accepted sequence is hook,
   setup, explanation, explanation, CTA with touching boundaries.
5. **Stage 5.3 improvements:** Partly. `08` retains all five scored labels and
   the end-card headline; `04` retains before/after and the corrected later
   sequence. `01` recovers product demo, and `12` removes both Stage 5.3
   overlaps. Aggregate Stage 5.4 label F1 (.800) and structure F1 (.824) are
   lower than Stage 5.3 (.857 and .933), chiefly due to disputed extra formats
   and `01`'s uncertain talking-head decision. Interval F1 improves from Stage
   5.3 at each tolerance but stays below Stage 5.2 at ±0.5 and ±1.0.
6. **Likely truth ambiguity:** `01` visible “grab yours” CTA, `04` clipper use as
   product demo and its first visible request, `08` product-action status of
   the quiz, and `12` listicle status of enumerated specialties merit
   independent ontology adjudication. `01` talking head and `04` opening hook
   need independent video review to distinguish conservative inference from
   missed evidence. These are disagreements, not automatically model errors.

The result meets stop rule **B**: the architecture no longer creates the
targeted format-coverage and structure-overlap failures, but the remaining
scored disagreements require independent review before any further semantic
changes. No further Stage 5.x tuning or seven-video extension was started.

## Checks and limits

- Focused Stage 5–5.4 and intelligence contract/evaluation tests: **64 passed**.
  Python compilation and `git diff --check` passed. Earlier artifact directory
  digest tests and exact-base diff check passed.
- Stage 5.4 candidate artifacts contain derived JSON only; no binary media,
  embedded images, API key, or private media path was found in the artifact
  privacy scan. Source video and decoded frames stayed outside Git.
- The provisional review is AI-assisted and non-blind. Sparse frames cannot
  establish every action or exact transition; source audio was not listened to
  independently. No independent human review, live-provider validation,
  production test, merge, deployment, or tag was performed.
