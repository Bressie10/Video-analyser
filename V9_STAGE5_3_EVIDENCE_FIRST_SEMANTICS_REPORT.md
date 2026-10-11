# V9 Stage 5.3 evidence-first semantic inference

**Decision: B — another targeted fix is needed.** Semantic candidate generation is not yet ready for independent review of the remaining seven videos. Do not run them.

## Scope and provenance

- Base: `3cf45f205a862d462c727a2f33843654c059da55`; branch: `codex/v9-stage5-3-evidence-first-semantics`.
- Inference was limited to `01 04 08 12`. The original Stage 5, 5.1, and 5.2 artifacts were not edited. No merge, deploy, or tag was performed.
- Every model call used requested/reported `gpt-6-sol`. Pass 1 prompt SHA-256: `88bc2d6d56ac3c6e232dadc4639fca62b6ad6126dbd57c8e031cb3065616ad4d`. Pass 2 prompt SHA-256: `8b950810bd422710ac87600edd7887d34fec981c295b8b5ab18e45d9cf0ebec9`. Frozen ontology `1.1.0` and report schema `2.0.0` remain unchanged.
- Per-call model, response ID, prompt SHA, and analyzer commit are in each [candidate JSON](backend/intelligence/evaluation/stage5_3/candidates/). Pass 1 calls used analyzer commit `c6a18c7` for `01`, `fc16490` for `04` and the first three `08` chunks, and `9b6efdc` for `12`. The `08` synthesis used `c48a277`. Later validation commits are recorded separately. The low-level pipeline commit remained `6cfbe673feb76e13a03c98f61533aa16c1cfcbad`.
- The model input used only private source frames, allowlisted Stage 2 transcript/OCR/scene evidence, and (in Pass 2) the frozen ontology and structure-role definitions. Pass 1 had no ontology definitions. Neither pass received performance, motion events, company history, prior recommendations, source audio, or Stage 5.1 truth. The truth path was opened only after all four candidate JSON files existed.

## What changed

The Stage 5.2 frame selector and OCR persistence summary were reused. The new analyzer partitions each runtime deterministically, sends each chunk's frames and relevant transcript/OCR/scene evidence to a description-only call, validates its references, and writes a derived [ledger JSON](backend/intelligence/evaluation/stage5_3/candidates/). A second call receives the complete ledger plus frozen definitions and explicitly assesses all whole-video formats, identifies physical CTA events, and maps evidence to techniques and structure. Each time-bounded finding needs an overlapping ledger item that traces to original evidence. `other` requires visible descriptive evidence. Structure coverage is not a target.

Model responses are checkpointed before local validation, with individual response provenance. Four zero-duration visual findings and one zero-duration structure segment in `08` could not satisfy the frozen interval schema; the candidate records them in `omitted_point_only_intervals` and omits them from the validated report. No interval was invented around a single still.

## Provisional comparison

Stage 5.1 truth is AI-assisted, non-blind, and partial. Only categories marked complete are scored; partial/unavailable categories abstain. These are reference-sensitivity measurements from four sources, not population accuracy. Exact matched indices, denominators, and precision/recall/F1 for every tolerance are in [side-by-side JSON](backend/intelligence/evaluation/stage5_3/side_by_side.json) and [per-video comparisons](backend/intelligence/evaluation/stage5_3/comparisons/).

| Source | Stage | Label TP/FP/FN | Label P/R/F1 | Interval TP at ±0.25 / ±0.5 / ±1.0s | Structure TP/FP/FN | Structure runtime fraction |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | Stage 5 | 4/0/0 | 1/1/1 | 2 / 3 / 3 | abstained | 0.990 |
| 01 | Stage 5.2 | 4/2/0 | 0.667/1/0.800 | 2 / 3 / 3 | abstained | 1.000 |
| 01 | Stage 5.3 | 3/2/1 | 0.600/0.750/0.667 | 1 / 3 / 3 | abstained | 0.990 |
| 04 | Stage 5 | 4/0/0 | 1/1/1 | 1 / 1 / 3 | abstained | 0.761 |
| 04 | Stage 5.2 | 3/1/1 | 0.750/0.750/0.750 | 0 / 0 / 2 | abstained | 1.000 |
| 04 | Stage 5.3 | 4/2/0 | 0.667/1/0.800 | 1 / 1 / 1 | abstained | 1.000 |
| 08 | Stage 5 | 4/0/1 | 1/0.800/0.889 | 3 / 3 / 3 | 3/0/0 | 1.000 |
| 08 | Stage 5.2 | 5/0/0 | 1/1/1 | 3 / 5 / 5 | 3/3/0 | 1.000 |
| 08 | Stage 5.3 | 5/0/0 | 1/1/1 | 2 / 3 / 4 | 3/1/0 | 0.518 |
| 12 | Stage 5 | 3/0/0 | 1/1/1 | 2 / 3 / 3 | 4/0/0 | 0.990 |
| 12 | Stage 5.2 | 3/0/0 | 1/1/1 | 2 / 3 / 3 | 4/1/0 | 0.998 |
| 12 | Stage 5.3 | 3/0/0 | 1/1/1 | 1 / 1 / 1 | 4/0/0 | 1.000 |

| Source | Missed reviewed findings Stage 5 → 5.2 → 5.3 | Unsupported findings Stage 5 → 5.2 → 5.3 | Contradictory structure pairs Stage 5 → 5.2 → 5.3 | Stage 5.3 ledger support failures | Whole-video formats Stage 5.2 → 5.3 |
| --- | --- | --- | --- | --- | --- |
| 01 | 0 → 0 → 1 (`format.product_demo`) | 0 → 2 → 2 (`hook.visual`, `cta.visual`) | 0 → 0 → 0 | 0 | `product_demo`, `talking_head` → `talking_head` |
| 04 | 0 → 1 → 0 | 0 → 1 → 2 (`hook.curiosity_gap`, `hook.story_open`) | 0 → 0 → 0 | 0 | none → `before_after` |
| 08 | 1 → 0 → 0 | 0 → 0 → 0 | 0 → 0 → 0 | 0 | `product_demo` → `product_demo` |
| 12 | 0 → 0 → 0 | 0 → 0 → 0 | 0 → 0 → **2** | 0 | `talking_head` → `talking_head` |

The `12` structure agreement count hides two incompatible overlapping role pairs: `hook`/`setup` and `explanation`/`cta`. Ledger items covered broad chunks, so the synthesis assigned multiple roles over the same intervals. All findings passed mechanical reference/timing checks, but that does not establish semantic correctness.

## CTA physical events and label overlap

| Source | Physical events | Labels per event | Overlapping label pairs in same event | Across different events |
| --- | ---: | --- | ---: | ---: |
| 01 | 1 | `verbal`, `visual`, `product` | 3 | 0 |
| 04 | 1 | `verbal`, `visual`, `product` | 3 | 0 |
| 08 | 2 | `visual`, `product` on each | 2 | 0 |
| 12 | 1 | `verbal`, `product` | 1 | 0 |

Grouping now distinguishes multiple ontology labels for one physical request from distinct events. It does not validate every CTA interpretation. The extra `01` visual CTA still disagrees with provisional review; `08`'s `cta.product` remains a semantic interpretation requiring independent review.

## Answers to the five evaluation questions

1. **Does 04 retain `format.before_after` while representing the later sequence?** Yes. Its format assessment cites six ledger items across the runtime, and the structural timeline includes 77.6–118.5s wheelchair/vehicle/foot-care observations plus 118.5–131.8s farewell views.
2. **Does the later 04 sequence stop being misdescribed?** Yes in this candidate. The ledger and synthesis describe care by the vehicle and a farewell; neither calls 118–131s food sharing. This remains a sparse-frame interpretation, not independently verified semantic truth.
3. **Does 08 retain the recovered end-card headline?** Yes. `text.headline` at 23.6–27.367s is present and matches provisional truth as a label; its interval is less precise than Stage 5.2.
4. **Does 01 avoid unsupported whole-video/CTA semantics from extra frames?** No. It avoids a new unsupported whole-video label but drops reviewed `format.product_demo` and retains a disputed `cta.visual` from visible “grab yours” text. Its ledger cites the words, while the ontology interpretation still needs review.
5. **Are good Stage 5.2 improvements preserved?** Partly. `04` keeps 29 selected frames and the 7.292s maximum gap, `08` retains the end-card headline and `format.product_demo`, and `12` retains its main labels. Stage 5.3 worsens interval timing on `04`, `08`, and `12`; `08` loses half its structure coverage after point-only omissions; `12` introduces overlapping roles; and `01` loses a reviewed format.

## Checks, risks, and next decision

- Focused Stage 5/5.1/5.2/5.3 and intelligence contract/evaluation tests: **49 passed**. Python compilation and `git diff --check` passed. SHA-256 immutability tests passed for original Stage 5/5.1/5.2 artifact directories.
- Privacy scan of Stage 5.3 artifacts found **zero** binary media files, embedded image data, API key copies, or private media paths. Only derived JSON, comparisons, and documentation are tracked.
- The evidence ledger provides auditable references, but semantic support still depends on model descriptions of sparse frames and detector text. There is no independent human review, source-audio assessment, or production validation. The key remaining targeted fix is finer temporal description/role boundaries for short clips and a more conservative whole-video/CTA synthesis decision; evaluate it without feeding provisional truth into inference.

**Final decision: B — another targeted fix is needed.** Do not automatically run the remaining seven videos.
