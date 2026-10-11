# Stage 5.1 provisional semantic review

The four Stage 5 pilot JSON outputs in `../stage5/pilot/` are immutable candidate predictions. `truth/` contains separate AI-assisted, non-blind review records. `comparisons/` contains derived evaluator output and Markdown audits. No source video, decoded frame, audio, or private media path is tracked here.

The reviewer inspected timestamped frames across each complete runtime at one-second spacing, except source 04 at 1.5-second spacing, with OCR/transcript context. Source audio was not listened to. This is a provisional visual review, not independent human or gold truth. Brief intervening edits, words, or overlays may be missed. Each category and structure review records `complete`, `partial`, or `unavailable` coverage; each reviewed item records its own coverage, status, timestamp, and rationale. Text usage that has no faithful frozen ontology label is described in adjudication notes rather than forced into an ontology item.

Run from `backend/`:

```sh
python -m intelligence.evaluation.stage5_1_review \
  --predictions-dir intelligence/evaluation/stage5/pilot \
  --truth-dir intelligence/evaluation/stage5_1/truth \
  --output-dir intelligence/evaluation/stage5_1/comparisons \
  --sources 01 04 08 12
```

The evaluator scores only categories marked complete. Partial and unavailable coverage abstain, so omitted truth items there never become false negatives. An uncertain reviewed item also abstains for a corresponding prediction. Label matching is one-to-one for the same ontology ID with at least 0.1 interval IoU; whole-video labels match whole-video labels. Interval matching separately requires both boundaries within ±0.25, ±0.5, or ±1.0 seconds. Structure-role agreement uses the same one-to-one role-and-overlap rule only when structure coverage is complete. Precision, recall, and F1 have `null` where the denominator is absent.

Duplicate same-technique intervals with IoU ≥0.7, overlapping CTA techniques with IoU ≥0.5, and incompatible overlapping structure roles are flagged rather than deleted. The evidence audit distinguishes interval support from context support using a 0.5-second tolerance. Future offline validation requires at least one temporally relevant frame, transcript, or OCR reference for each time-bounded finding and structure segment. A scene reference alone does not establish semantic support. Whole-video format labels may cite contextual evidence. Timing support does not prove visual or linguistic interpretation; manual adjudication remains necessary.
