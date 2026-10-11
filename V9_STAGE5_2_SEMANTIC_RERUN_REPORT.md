# V9 Stage 5.2 semantic baseline targeted rerun

**Decision: B — another targeted semantic fix is needed.** Do not infer on the remaining seven videos.

## Exact provenance and isolation

- Branch: `codex/v9-stage5-2-semantic-rerun`, based on Stage 5.1 commit `38956f45976d0d1d9e1392825fb1a248debfa4a9`.
- Inference analyzer commit: `1c376da9fb37bf35738df83b2d7a9e665e304b17` (committed before any Stage 5.2 inference). Low-level inputs retain pipeline commit `6cfbe673feb76e13a03c98f61533aa16c1cfcbad`.
- Requested and reported model: `gpt-6-sol`. Prompt SHA-256: `35a641ed3011b695e219145fea591df252681189ea407e031a734a33a02a9505`. Frozen ontology `1.1.0`; frozen report schema `2.0.0`. Full prompt, OpenAI SDK version, response ID, selected decoded frame timestamps/reasons/hashes, OCR summary supplied, and frame coverage are in each [candidate JSON](backend/intelligence/evaluation/stage5_2/candidates/).
- Response IDs: `01` `resp_08bf3d347b4f3b6e016acb7470ff5087d2ac09c6f3617ccdb1`; `04` `resp_0bce8a0621f827a1016acb74817e3887d2bd33956c4a2295b7`; `08` `resp_04efd42580b8595b016acb748e0b4487d2aa29eb8186b40f8e`; `12` `resp_048febd1b10d697d016acb749920dc87d28010c9e1593337fc`.
- Inference read only private source video, Stage 2 low-level analysis, and frozen ontology definitions. The reviewed truth path was passed **only after all four model calls completed** to the Stage 5.1 evaluator and side-by-side comparison. No truth, performance, motion, company history, previous recommendations, or source audio entered the semantic model request.
- All Stage 5 candidates and Stage 5.1 truth/comparisons are unchanged. New predictions and derived comparisons are in `backend/intelligence/evaluation/stage5_2/`. No private media, decoded frame image, or audio is tracked.

## Generator changes

- Deterministic duration-aware frame selection keeps opening and final frames, regular temporal anchors, useful OCR changes, and sampled scene representatives, capped at 32. Optional near-duplicate scene frames are skipped. Short sources used 11–16 frames; the 138.5-second source used 29.
- A derived OCR summary groups **only consolidated OCR observations** by normalized text. It records first/last appearance, approximate union-of-span persistence, consolidated span count, repeated non-contiguous occurrence count, and source OCR references. It does not synthesize missing words.
- Prompt guidance now asks for structure across the supplied runtime, distinguishes persistent directive text from captions/headlines, and requires independent ontology support and aligned timing for multiple CTA labels on one event. It does not change the frozen ontology or force a label for uncovered intervals.
- Stage 5.1 comparison now reports `structure_covered_runtime_fraction`, the union of predicted structure intervals divided by runtime. It is descriptive, not a coverage target or semantic correctness measure.

## Visual coverage and candidate changes

| Source | Frames Stage 5 → 5.2 | Largest gap Stage 5 → 5.2 | Structure-covered runtime Stage 5 → 5.2 | What changed |
| --- | ---: | ---: | ---: | --- |
| `01` | 15 → 16 | 4.667s → 3.967s | 0.990 → 1.000 | Core perfume claim, talking head, product demo, captions, and purchase CTA remain. Candidate adds `hook.visual` and `cta.visual`, which are disagreements with current provisional truth and require review; CTA overlap pairs rise 1 → 3. |
| `04` | 14 → 29 | **28.417s → 7.292s** | 0.761 → 1.000 | Later wheelchair and leg-cleaning/bandaging footage is now represented. Candidate loses the previously detected `format.before_after` and reviewed `hook.visual`, and calls 118–131s food-sharing although the reviewed visual samples show the treatment/farewell sequence there. The larger structure fraction therefore overstates useful coverage. |
| `08` | 14 → 16 | 5.800s → 6.867s | 1.000 → 1.000 | Persistent quiz overlay remains recognized as a visual CTA; the end-card `text.headline` is now detected. The overlay has no faithful generic frozen text technique, so no text label was forced. `cta.product` remains an uncertain interpretation and CTA overlap pairs stay at 2. |
| `12` | 10 → 11 | 8.900s → 7.167s | 0.990 → 0.998 | Question hook, talking-head format, and course-catalog CTA remain. No unsupported text/audio technique was added. The new 0.27s `other` tail adds coverage but little semantic value. |

Source `08`'s slightly larger maximum gap is still below eight seconds and the short-video frame count remains bounded. A frame gap measures sampling, not whether the model interpreted the frames correctly.

## Separate provisional comparison measures

The same **AI-assisted, non-blind provisional Stage 5.1 truth** was applied to both generations only after inference. Partial/unavailable categories abstain, so many findings and the `01`/`04` structure timelines are unscored. These are small-pilot reference-sensitivity measures, **not semantic accuracy or population estimates**. [Side-by-side JSON](backend/intelligence/evaluation/stage5_2/side_by_side.json) retains exact denominators, matches, and precision/recall/F1 for every tolerance.

| Source | Label TP/FP/FN Stage 5 → 5.2 | Label P/R/F1 Stage 5 → 5.2 | Interval TP at ±0.25 / ±0.5 / ±1.0s Stage 5 → 5.2 | Structure-role TP/FP/FN Stage 5 → 5.2 |
| --- | --- | --- | --- | --- |
| `01` | 4/0/0 → 4/2/0 | 1/1/1 → 0.667/1/0.800 | 2/3/3 → 2/3/3 | abstained / abstained |
| `04` | 4/0/0 → 3/1/1 | 1/1/1 → 0.750/0.750/0.750 | 1/1/3 → 0/0/2 | abstained / abstained |
| `08` | 4/0/1 → 5/0/0 | 1/0.800/0.889 → 1/1/1 | 3/3/3 → 3/5/5 | 3/0/0 → 3/3/0 |
| `12` | 3/0/0 → 3/0/0 | 1/1/1 → 1/1/1 | 2/3/3 → 2/3/3 | 4/0/0 → 4/1/0 |

| Source | Same-technique heavy-overlap pairs | Overlapping CTA pairs Stage 5 → 5.2 | Contradictory structure pairs | Interval-support failures | Missed reviewed findings Stage 5 → 5.2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `01` | 0 → 0 | 1 → 3 | 0 → 0 | 0 → 0 | 0 → 0 |
| `04` | 0 → 0 | 3 → 3 | 0 → 0 | 0 → 0 | 0 → 1 |
| `08` | 0 → 0 | 2 → 2 | 0 → 0 | 0 → 0 | 1 → 0 |
| `12` | 0 → 0 | 1 → 1 | 0 → 0 | 0 → 0 | 0 → 0 |

The [per-video Stage 5.2 comparisons](backend/intelligence/evaluation/stage5_2/comparisons/) preserve matched indices, unsupported counts, temporal support and context references, duplicate/CTA/structure flags, and category abstentions. The evaluator flags overlapping CTA labels for adjudication; they are not automatically false. Zero temporal-support failures proves cited timing proximity, not semantic validity.

## Answers to the targeted questions

1. **Better long-video coverage?** Yes for `04`: 29 supplied frames and a 7.292s maximum gap, compared with 14 frames and 28.417s.
2. **Fewer missed later sequences?** Partly. The `04` candidate now names leg care and transport, but misinterprets the later timeline and loses an established format label. Broader sampled coverage has not yet yielded reliable full-structure interpretation.
3. **Persistent OCR/text more consistent?** The `08` overlay remains recognized as a CTA, and the deterministic summary explicitly exposes persistence. It did not create a new text technique, consistent with the frozen ontology. No clear improvement in persistent-overlay labeling can be claimed beyond that.
4. **End-card text more consistent?** Yes for `08`: the previously missed end-card headline is now found, with ±0.5s interval match to provisional truth.
5. **Fewer duplicated CTA findings?** No. Same-technique heavy overlaps remain zero, but overlapping CTA pairs stay unchanged for three sources and increase on `01`.
6. **Good Stage 5 findings retained?** Mostly for `01`, `08`, and `12`; not fully for `04`, where `format.before_after` and `hook.visual` disappear. Some new `01` findings may be real but conflict with incomplete provisional review; preserve that disagreement for an independent reviewer rather than relabeling truth to improve scores.

## Next fix before another four-video rerun

Keep the duration-aware sampling and OCR summary. Target the inference decision process: require explicit comparison of whole-video format evidence, prevent `other` intervals from merely filling runtime, and make later-sequence descriptions cite the actual supplied frames rather than inferred context. Revisit CTA overlap guidance with independent review of whether multiple labels describe the same physical request. Then rerun these four only; do not expand to seven remaining videos.

## Checks and files

- Focused Stage 5/5.1/5.2 tests: 18 passed. Focused intelligence tests: 21 passed. Python compilation, artifact privacy scan, and `git diff --check`: passed. Original Stage 5 candidates and Stage 5.1 truth/comparisons passed fixed SHA-256 immutability checks.
- Changed code/tests: `backend/intelligence/evaluation/stage5_semantic.py`, `backend/intelligence/evaluation/stage5_1_review.py`, `backend/intelligence/evaluation/stage5_2_compare.py`, `backend/tests/test_stage5_semantic.py`, `backend/tests/test_stage5_2_semantic.py`.
- Added documents/artifacts: `backend/intelligence/evaluation/stage5_2/README.md`, `backend/intelligence/evaluation/stage5_2/candidates/{01,04,08,12}.{selection.json,json,md}`, `backend/intelligence/evaluation/stage5_2/comparisons/{01,04,08,12}.{json,md}`, `backend/intelligence/evaluation/stage5_2/side_by_side.json`, and this report.

**Final recommendation: B — another targeted semantic fix is needed.**
