# Stage 5.4 format semantics and atomic structure

This offline, two-pass experiment is restricted to source videos `01 04 08 12`.
Pass 1 receives selected frames and allowlisted transcript, OCR, and scene
observations in temporal chunks. It produces atomic descriptions with an
evidence-backed boundary reason. Pass 2 receives the complete ledger, frozen
ontology definitions, and controlled structure roles. Neither pass receives
reviewed truth, performance, or motion. Source video and decoded frames stay
outside Git.

Run from `backend/` after committing the analyzer and loading `OPENAI_API_KEY`:

```sh
python -m intelligence.evaluation.stage5_4_semantic \
  --manifest /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output-dir intelligence/evaluation/stage5_4/candidates \
  --sources 01 04 08 12
```

Each candidate records model, response ID, prompt hashes, analyzer commit,
ledger, format assessments, CTA events, and validated report. Checkpoints
persist model responses before validation and allow resumption with matching
prompt hashes and low-level content. When a model interval extends beyond its
cited atomic evidence, unsupported outer edges are trimmed and recorded in
`synthesis_timing_adjustments`; unsupported internal gaps and incompatible
primary structure roles still fail validation. Only after all four candidates
exist, run:

```sh
python -m intelligence.evaluation.stage5_4_compare \
  --stage5-2-dir intelligence/evaluation/stage5_2/candidates \
  --stage5-3-dir intelligence/evaluation/stage5_3/candidates \
  --stage5-4-dir intelligence/evaluation/stage5_4/candidates \
  --truth-dir intelligence/evaluation/stage5_1/truth \
  --results /private/tmp/cm-v9-pilot/results-stage2 \
  --output intelligence/evaluation/stage5_4/side_by_side.json
```

Stage 5.1 truth is AI-assisted, non-blind, and provisional. Partial and
unavailable categories abstain in comparison; disagreement is not automatic
evidence that the candidate is wrong.
