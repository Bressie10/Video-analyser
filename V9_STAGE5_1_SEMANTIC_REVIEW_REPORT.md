# V9 Stage 5.1 semantic pilot review and adjudication

**Decision: B — rerun these four after targeted fixes.** Keep semantic inference offline. Do not expand to all 11 videos yet.

## Provenance and scope

- Branch `codex/v9-stage5-1-semantic-review` starts at Stage 5 commit `42b0906f65626de89a886c79f18f1854a02ff120`. Original Stage 5 prediction files for `01`, `04`, `08`, and `12` retain their base-commit SHA-256 hashes; they were not overwritten.
- Four separate [reviewed truth records](backend/intelligence/evaluation/stage5_1/truth/) identify source video SHA-256, reviewer type, review method, model visibility, blind status, per-category coverage, each item's status/timing/evidence, and adjudication notes.
- Review is **AI-assisted, non-blind, provisional**, with no independent human reviewer and no gold truth. Timestamped frames were inspected across each complete source runtime at 1-second spacing (`04`: 1.5 seconds), alongside existing OCR and transcript. Source audio was not listened to. Brief events between frames may be missed, so editing and much visual/text review remain partial; audio is unavailable.
- No production route, storage, frontend, schema, ontology, or recommendation behavior changed. No private media or extracted frame image is committed.

## Per-video adjudication

| Source | Reviewed finding | Resolution and remaining uncertainty |
| --- | --- | --- |
| `01` | Long `text.captions` span | Speech-following captions appear throughout the one-second samples from roughly 0.5–28.7s. Retain as provisional present with **partial** text coverage because intervening gaps are unobserved. |
| `01` | `editing.b_roll` | Product close-ups around 2.6–6.5s and 11.9–15.9s support the B-roll interpretation. Editing coverage stays partial; exact cut boundaries need continuous review. Structure boundaries are reviewed separately and remain partial, including an uncertain `proof` role for an unverified speaker claim. |
| `04` | Grooming and reveal | Grooming starts near 15s and runs through about 70s; the dressed/groomed reveal is about 70–80.5s. A wheelchair sequence follows, then **foot care and bandaging around 89–130.5s**, a major sequence the Stage 5 structure largely missed. The long transcript “Bye” spans were not used as timing truth. |
| `04` | CTA overlap | The visible “buy yours today” request supports both `cta.visual` (modality) and `cta.product` (purchase action) at the end. They describe one event, not two independent requests. `cta.verbal` remains uncertain because audio was not heard. |
| `08` | CTA duplication and text use | The overlay quiz request persists through roughly 0–23.5s, followed by a separate end card whose quiz button appears around 24.8s. Two `cta.visual` intervals reflect two presentations. `cta.product` is **uncertain**: quiz/guide is a funnel action, but no product visit or purchase is explicit. Persistent directive text is recorded in an adjudication note because the frozen text ontology has no generic overlay label; the end-card `text.headline` is present and was missed by Stage 5. |
| `12` | Text and talking head | No text appears in one-second samples, recorded as provisional absent with **partial** coverage. Talking-head format is supported by repeated lens-facing samples, without asserting one uninterrupted shot. Transcript proper names were not adopted as identity facts. |

Each [comparison audit](backend/intelligence/evaluation/stage5_1/comparisons/) gives the exact provisional items, matched indices, evidence support, and flags. The source videos need independent complete playback and audio review before any truth promotion.

## Separate evaluator results

Only complete categories contribute to the counts below. Partial/unavailable categories abstain; uncertain items do not create false positives or negatives. These values describe this small, non-blind pilot and are **not semantic accuracy or population estimates**.

| Source | Label TP/FP/FN | Label P/R/F1 | Interval TP at ±0.25 / ±0.5 / ±1.0 s | Structure-role agreement | Unscored predictions |
| --- | --- | --- | --- | --- | ---: |
| `01` | 4/0/0 | 1.00 / 1.00 / 1.00 | 2 / 3 / 3 | abstained: partial structure | 9 |
| `04` | 4/0/0 | 1.00 / 1.00 / 1.00 | 1 / 1 / 3 | abstained: partial structure | 4 |
| `08` | 4/0/1 | 1.00 / 0.80 / 0.89 | 3 / 3 / 3 | 3 TP, 0 FP, 0 FN | 4 |
| `12` | 3/0/0 | 1.00 / 1.00 / 1.00 | 2 / 3 / 3 | 4 TP, 0 FP, 0 FN | 1 |

The full interval precision/recall/F1 and denominators for each tolerance are in JSON. The confirmed scored miss is `08`'s end-card headline. `04`'s large structure omission is visible in review but deliberately unscored while structure coverage is partial.

| Source | Same-technique heavy overlaps | Overlapping CTA-technique pairs | Contradictory structure pairs | Findings lacking interval support | Unsupported / missed scored findings |
| --- | ---: | ---: | ---: | ---: | ---: |
| `01` | 0 | 1 | 0 | 0 | 0 / 0 |
| `04` | 0 | 3 | 0 | 0 | 0 / 0 |
| `08` | 0 | 2 | 0 | 0 | 0 / 1 |
| `12` | 0 | 1 | 0 | 0 | 0 / 0 |

CTA pair flags are overlap prompts for adjudication. They are not proof that one label is wrong. Zero temporal-support failures means at least one cited frame/OCR/transcript item fell within or near each bounded claim; it does **not** establish that the content of the reference supports the label.

## Evaluator hardening

- New offline evaluator validates provisional truth against frozen ontology IDs and controlled structure roles, checks provenance/coverage, computes one-to-one label and interval matches at three tolerances, scores structure roles separately, and flags duplicate/overlapping/contradictory predictions.
- Stage 5 offline validation now classifies each citation as `interval_support` or `context_support` and requires a temporally relevant non-scene reference for time-bounded findings and structure segments. Whole-video format labels may use context. The original four candidate outputs pass the stronger validator without modification.
- Semantic model input remains allowlisted; motion and performance fields remain excluded. No automatic deletion or production promotion occurs.

## Next targeted fixes

1. Improve long-video frame coverage or add a second visual pass so `04`'s post-reveal aid sequence is represented in the candidate structure.
2. Teach inference to distinguish persistent CTA overlay text from speech captions and to capture the `08` end-card headline without inventing a new ontology label.
3. Clarify ontology guidance for `cta.visual` plus `cta.product` on the same event, and refine interval boundaries for the closing quiz button.
4. Obtain independent reviewer playback of all four complete videos, including audio if verbal/audio technique labels will be scored. Preserve disagreements and adjudicate before treating coverage as complete.

After these fixes, rerun only `01`, `04`, `08`, and `12` and inspect the candidate/truth contract again. **Recommendation: B.**

## Checks and changed files

- Focused Stage 5/5.1 tests: 11 passed. Focused intelligence tests: 21 passed. Python compilation: passed. All four original predictions pass the strengthened temporal validator. `git diff --check`: passed.
- Candidate preservation: SHA-256 checks cover all 12 original Stage 5 pilot JSON, Markdown, and selection files; the Stage 5 pilot directory is absent from this branch diff.
- Changed files: `backend/intelligence/evaluation/stage5_semantic.py`, `backend/intelligence/evaluation/stage5_1_review.py`, `backend/tests/test_stage5_1_review.py`, `backend/intelligence/evaluation/stage5_1/README.md`, `backend/intelligence/evaluation/stage5_1/truth/{01,04,08,12}.json`, `backend/intelligence/evaluation/stage5_1/comparisons/{01,04,08,12}.json`, `backend/intelligence/evaluation/stage5_1/comparisons/{01,04,08,12}.md`, and `V9_STAGE5_1_SEMANTIC_REVIEW_REPORT.md`.
