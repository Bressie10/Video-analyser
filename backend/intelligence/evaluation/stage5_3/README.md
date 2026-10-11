# Stage 5.3 evidence-first semantic inference

This offline experiment has two explicit model stages. Pass 1 receives one deterministic temporal chunk with its selected frames, transcript, OCR, OCR persistence summary, and scene timing. Its strict output is observable descriptions with original evidence references. Pass 2 receives the complete ledger, OCR summary, frozen ontology definitions, and controlled structure roles. It returns format assessments, physical CTA events, ontology findings, and structure intervals citing ledger IDs. Validation traces those IDs to supplied frame, transcript, or OCR references and checks interval overlap. No source audio techniques are inferred.

Stage 5.2 frame selection and OCR summary are reused. Source video and decoded frames stay outside Git. The inference command accepts only `01 04 08 12`, and has no truth path. Run from `backend/` after committing the analyzer:

```sh
python -m intelligence.evaluation.stage5_3_semantic \
  --manifest /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output-dir intelligence/evaluation/stage5_3/candidates \
  --sources 01 04 08 12
```

Set `OPENAI_API_KEY` through the local environment before running. Each candidate records every pass's requested/reported model, response ID, prompt SHA-256, and analyzer commit. A separate `*.ledger.json` stores the derived Pass 1 observations. Compare with provisional Stage 5.1 truth only after all four candidates finish. Stage 5.1 truth is AI-assisted and non-blind; partial and unavailable categories abstain.

Each `*.checkpoint.json` records model responses before local validation and permits a safe resume when prompts and allowlisted content match. A validation fix can have a later `validation_commit`; the per-pass records keep the analyzer commit that actually generated each response. Point-only claims with zero duration are retained in `omitted_point_only_intervals` and omitted from the frozen interval report.

After all four inference outputs exist, run:

```sh
python -m intelligence.evaluation.stage5_3_compare \
  --stage5-dir intelligence/evaluation/stage5/pilot \
  --stage5-2-dir intelligence/evaluation/stage5_2/candidates \
  --stage5-3-dir intelligence/evaluation/stage5_3/candidates \
  --truth-dir intelligence/evaluation/stage5_1/truth \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output intelligence/evaluation/stage5_3/side_by_side.json
```
