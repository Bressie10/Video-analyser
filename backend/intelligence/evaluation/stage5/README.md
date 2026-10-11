# V9 Stage 5 offline semantic baseline

This experiment turns existing low-level analysis and selected private source frames into provisional V8.5 ontology observations. It does not call production routes, read performance data, use `motion_events`, or change stored analysis. Its output is **not semantic accuracy** and must be manually reviewed against the video.

The model receives only duration, frame size/FPS, transcript segments, consolidated OCR spans, scene intervals, the frozen ontology, the controlled structure roles, and selected JPEG frames. A source video remains private. The frame selector records actual decoded timestamps and JPEG hashes in JSON; JPEG bytes exist only in memory for the model request. Opening, scene, OCR-change, and final regions are sampled, capped at 16 images, with near-duplicate interior frames skipped.

The first pilot is limited to `01 04 08 12`. Prepare the exact frame plan without a model call:

```sh
cd backend
python -m intelligence.evaluation.stage5_semantic \
  --manifest /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output-dir intelligence/evaluation/stage5/pilot \
  --sources 01 04 08 12 --prepare-only
```

For model inference, omit `--prepare-only` and set `OPENAI_API_KEY`; optionally set `OPENAI_MODEL`. The command writes one JSON and one Markdown audit per source. JSON contains the exact prompt and its hash, requested and reported model, response ID, SDK version, low-level pipeline commit, analyzer commit, ontology version, allowlisted-content hash, selected frame timestamps and hashes, cited evidence excerpts, the structured model draft, and a validated frozen `AnalysisReport`. A model alias may not disclose an immutable weights version; the requested/reported strings are all the provider exposes here. The offline draft preserves `direct_observation` versus `model_interpretation`; the frozen report schema is not changed. A model label without an ontology ID, supplied evidence reference, valid time, confidence, or rationale is rejected. There is no automatic score or promotion to production.

Review each finding against private media for label support, timestamp quality, duplicates, contradictions, missing techniques, unsupported subject or audience assumptions, and invented words. Sparse still frames cannot establish continuous motion, audible music/effects, or precise edit transitions. A scene boundary by itself is timing evidence, not an editing label. OCR/transcript text may be wrong and must be treated as untrusted content. No two-human or gold truth provenance is claimed for this pilot.
