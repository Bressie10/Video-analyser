# ContentMetric V9 Stage 1 calibration report

Status: **workflow ready; real-media measurement pending**. This report records the evidence available in the repository at implementation time. No authorized 10–15 video pilot media, independent human annotations, or reviewed low-level truth were supplied to this worktree. All numerical checks below are synthetic software checks, not estimates of field performance.

## Pilot dataset composition

| Item | Real-media result |
|---|---|
| Videos and creator groups | 0 supplied; target 10–15 videos from at least five groups, with at most three from one known creator |
| Variation | Pending: talking head, tutorial, product demo, screen recording, interview, storytime, before/after; fast/slow editing; captions/no captions; music/no music; clean/noisy audio; simple/busy scenes; weak/ordinary/strong content |
| Media provenance and rights | Pending private manifest; no third-party media committed |
| Train/validation/test grouping | Supported; no real assignments yet |

The pilot selection and near-duplicate exclusion must be documented before annotation. A convenience sample of 10–15 cannot support broad creator, platform, genre, or language claims.

## Annotation agreement

Guideline **1.1.0** and frozen V8.5 `Annotation` contracts remain in use. The semantic workflow requires two independent pseudonymous records per source, explicit category/structure/numeric coverage, uncertainty notes, a source-level split/group, an agreement JSON, adjudication notes, and a third reviewed truth record. Original disagreements remain in the two first-pass files. Real semantic agreement statistics: **unavailable (0 annotated pilot videos)**. Agreement will be reported by technique presence, interval IoU, point timing, and structure role, with incomplete coverage excluded from that comparison.

Low-level truth now has a separate **private Stage 1 format version 1.0.0**. Two independent records carry annotator pseudonyms and timezone-aware annotation times; a reviewed record carries a separate reviewer pseudonym and review time. An offline audit requires both originals and nonempty adjudication notes before a source can be scored. Its per-signal agreement report compares scene timing, OCR spans/text, transcript text/timed segments, motion overlap/type, and independently checked metadata. Partial and unavailable coverage is excluded. Real low-level agreement statistics: **unavailable (0 annotated pilot videos)**. Human truth must be finalized before anyone involved sees V8 output.

## Existing V8 signal results

| Signal | Pilot metric and uncertainty plan | Real-media result |
|---|---|---|
| Editorial scene boundaries | Precision, recall, F1 at 0.1/0.25/0.5 s; matched timing error; Wilson 95% intervals on event proportions | Pending |
| OCR visible text | Exact normalized-text precision/recall; text similarity; temporal IoU; unmatched visible text span rate | Pending |
| Transcript/ASR | Token error rate; segment timing only when texts align; missing/hallucinated speech segment-presence counts | Pending |
| Human-observable motion | Presence precision/recall/F1, temporal overlap, false positives/negatives, V8 type confusion | Pending |
| Metadata | Independently checked duration, resolution, FPS, each with an explicit tolerance; per-field correctness | Pending |

No overall “analysis accuracy” is computed. The evaluator keeps per-source rows and micro event counts. Wilson intervals describe event proportions, not uncertainty over creators or genres; sources within a creator group are correlated. For any final report, add group-level resampling or an explicit small-sample uncertainty statement and show all denominators. Do not interpret undefined rates from empty truth/prediction sets as zero.

`unmatched_visible_text_span_rate` counts visible truth spans with no OCR track having any positive temporal overlap. A paired track with the wrong text lowers exact-text recall but does not count as an unmatched span. Transcript missing/hallucinated segment counts describe temporal segment presence, not recognition correctness.

## Detector coverage, abstention, and missing data

Real detector coverage is **unknown**. Each reviewed low-level truth file marks every signal `complete`, `partial`, or `unavailable`. Only `complete` is scored; a complete empty list is a checked negative. Partial/unavailable sections abstain. Missing result or reviewed truth files are counted separately as missing data. Independent draft records cannot be scored. Silent media may yield empty ASR output through the existing pipeline. Pipeline exceptions stop processing that source; they must be reported as coverage failures, not suppressed as clean negatives. The runner records the pipeline commit and input hash alongside raw output outside the production database.

## Failure examples and taxonomy

No real failures have been observed, so **no pilot failure category is assigned**. During review, log source/time, independent truth, raw output, human evidence, category, and reviewer for each observed mismatch. Inspect the task's suggested scene, OCR, ASR, and motion categories, but include a category only when a real example supports it. The synthetic fixture exercises deliberate matches, misses, false predictions, motion type confusion, empty truth, and abstention; these are test cases, not field examples.

## Synthetic fixtures versus real media

Existing generated-media and synthetic fixtures can establish that the pipeline runs and that evaluation math handles known events. They cannot measure stylized captions, noisy or accented speech, gradual transitions, camera/subject motion ambiguity, editing density, compression artifacts, or real-world domain variation. A passing generated-media check therefore provides no real-media accuracy claim. The exact differences remain **unmeasured** until the pilot is run.

## Derived-feature trust and next decision

Current derived features are **not yet validated for real-media interpretation by Stage 1**. Keep scene boundaries, OCR, transcript, motion, and metadata distinct from semantic/editorial conclusions. In particular, a V8 `cut_timestamp_seconds` is a scene detector output, not proof of an editorial cut; optical-flow types are heuristic, not a guaranteed camera-action label.

**Next evidence priority:** acquire and annotate the authorized, varied 10–15 clip pilot, run the unchanged V8 pipeline, and inspect per-signal errors. **Next detector: undecided.** Choose between scene/change detection, ASR/timing, OCR tracking, motion interpretation, missing audio evidence, or missing visual evidence only after comparing measured failure severity and coverage. No stage-gate recommendation about a new detector is justified with zero real pilot videos.

No production API, DB, frontend, model, semantic detector, recommendation, billing, auth, or Meta behavior was changed.
