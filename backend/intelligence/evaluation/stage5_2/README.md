# Stage 5.2 offline four-video rerun

This branch changes only the offline semantic candidate generator and evaluator. Original Stage 5 candidates and Stage 5.1 provisional truth/comparisons remain immutable. Reviewed truth has no path into the inference command or allowlisted model payload; it is read only by comparison commands after inference completes. No performance, motion, company history, prior recommendations, or audio waveform enter inference.

The deterministic selector keeps opening and final frames, adds regular temporal anchors, then uses remaining slots for OCR changes and scene representatives. It caps selection at 32 frames, with fewer frames for short videos. Optional scene frames that resemble already supplied frames are skipped; regular coverage anchors remain so a long source does not develop an unobserved gap merely because a shot repeats. Every output records decoded timestamps, selection reasons, frame count, and the largest gap including the start/end edges.

`derived_ocr_summary` groups consolidated OCR by normalized observed text and records first/last appearance, approximate union-of-span persistence, number of consolidated spans, repeated non-contiguous occurrence count, and exact source OCR references. It does not join neighboring words or create new text.

Run from `backend/` after committing the analyzer implementation so `analyzer_commit` identifies the exact inference code:

```sh
python -m intelligence.evaluation.stage5_semantic \
  --manifest /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output-dir intelligence/evaluation/stage5_2/candidates \
  --sources 01 04 08 12 --prepare-only
```

Omit `--prepare-only` with `OPENAI_API_KEY` set to make the four model calls. This writes separate candidate JSON and Markdown files. Only then compare against provisional Stage 5.1 truth:

```sh
python -m intelligence.evaluation.stage5_1_review \
  --predictions-dir intelligence/evaluation/stage5_2/candidates \
  --truth-dir intelligence/evaluation/stage5_1/truth \
  --output-dir intelligence/evaluation/stage5_2/comparisons \
  --sources 01 04 08 12
python -m intelligence.evaluation.stage5_2_compare \
  --baseline-dir intelligence/evaluation/stage5/pilot \
  --candidate-dir intelligence/evaluation/stage5_2/candidates \
  --truth-dir intelligence/evaluation/stage5_1/truth \
  --output intelligence/evaluation/stage5_2/side_by_side.json \
  --sources 01 04 08 12
```

Stage 5.1 truth is non-blind AI-assisted provisional review based on timestamped visual samples, without source-audio review. Its partial/unavailable categories abstain. Comparisons are reference-sensitivity audits, not semantic accuracy or population estimates. Source videos and extracted frames remain private and outside Git.
