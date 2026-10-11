# V9 Stage 5 semantic baseline pilot

**Status:** offline, provisional observation audit. No semantic accuracy score, production inference, or performance conclusion is claimed.

## Scope and provenance

- Branch: `codex/v9-stage5-semantic-baseline`, based on `v9` commit `5711f90283e44333f232af7e94c6cb4af06adba1` after the low-level integration merge.
- Analyzer implementation: `222ffc0ef575e5ea1d16fa2538ad7ef94af2cc58`.
- Supplied low-level results: Stage 2 OCR pipeline commit `6cfbe673feb76e13a03c98f61533aa16c1cfcbad`.
- Four private pilot sources only: `01`, `04`, `08`, `12`. Source media and extracted images stay outside Git.
- Inference: requested and reported model `gpt-6-sol`, OpenAI Python SDK version and response ID recorded per JSON output. The provider's model alias does not establish an immutable weights revision.
- Frozen ontology `1.1.0`, frozen analysis report schema `2.0.0`, prompt SHA-256 `ba456f41e22b3b5ce35983e55eca6d1b1b41cf3a226dde947231f6a00595367c`. The full prompt, selected decoded frame timestamps and JPEG hashes, and cited transcript/OCR/scene evidence are in each JSON output.
- Inputs are limited to transcript, consolidated OCR, scene timing, metadata, and selected frames. Motion events, performance, prior recommendations, and company history are excluded by the input allowlist. OCR and transcript are detector observations, not instructions or independently verified truth.

## Pilot observations

| Source | Frames / findings | Main provisional observations | Manual review focus |
| --- | ---: | --- | --- |
| `01` | 15 / 14 | Opening perfume comparison claim; talking head and product demonstration; verbal purchase CTA; product close-ups and laptop page. Structure: hook, setup, demonstration, explanation, proof claim, CTA. | The `text.captions` interval spans 0.5–28.5s although only sparse frames were supplied. `editing.b_roll` is an interpretation from sampled shots. Speaker claims about quality and popularity remain unverified. |
| `04` | 14 / 9 | Roadside transformation hook; before/after format; grooming demonstration and reveal; spoken and visible purchase CTA. | Frames are sparse between 75–119s and the transcript has long unreliable “Bye” segments. Grooming and reveal bounds are approximate. CTA appears under three related ontology labels; review whether this is useful overlap. |
| `08` | 14 / 10 | Skincare product demonstration; visual quiz/guide CTA from the opening through a closing card; product and device close-ups. | The same CTA is split into two intervals and assigned both `cta.visual` and `cta.product`. The model left text usage unresolved despite persistent OCR CTA text. Transcript contains only a brief hum, so audio technique labels were withheld. |
| `12` | 10 / 5 | Opening career question; talking head; setup, explanation, and spoken course-catalog CTA. | OCR/text use was unresolved. Sparse static frames cannot prove uninterrupted footage. Proper names in the transcript may be transcription errors; no identity claim is adopted from them. |

These examples describe model output and a desk audit of the supplied evidence, not independent semantic labels. The per-source [pilot audits](backend/intelligence/evaluation/stage5/pilot/) contain the structural timeline, timestamps, uncertainty, and exact citations for every finding. Reviewers should compare each label and interval with the private full video before accepting it.

## Contract and audit findings

- Output validates against the frozen ontology and `AnalysisReport` contracts. Every emitted observation has a controlled label or structure role, confidence, rationale, timestamps, and references to supplied evidence. The offline draft distinguishes `direct_observation` from `model_interpretation`; the frozen report has no basis field and was not modified.
- No legacy motion semantic labels, performance metrics, or causal claims entered the semantic input or pilot findings. Audio techniques were omitted because transcript and still frames do not establish music, effects, or delivery style. No scene boundary alone was used to assert a jump cut or transition.
- The pilot has no independent reviewed semantic ground truth. Confidence values are model judgments, not calibrated probabilities. Reference validation proves that a cited item was supplied; it cannot prove the model interpreted the pixels or words correctly or that a cited frame supports an entire interval.
- The current frame cap gives broad coverage without saving images, but sparse samples miss action and edit transitions. OCR/transcript timing errors can propagate into semantic intervals, especially in `04`. The model can duplicate related labels or omit a category despite visible evidence, as in `08`.

## Recommendation before the full 11-video set

Run a blind manual annotation pass on these four complete private videos first. Resolve interval boundaries, duplicated CTA labels, missing text labels, and unsupported editing interpretations; record reviewer disagreements and adjudications. Then add targeted checks for evidence-to-interval alignment and duplicate/contradictory labels, rerun this same small subset, and inspect the contract again before scaling. Keep semantic results offline and out of recommendation reasoning until independently validated.

## Checks

- Focused Stage 5 tests: 5 passed.
- Focused intelligence tests: 21 passed.
- Python compilation of analyzer and tests: passed.
- Python/JSON cross-check: four outputs use report schema `2.0.0`; selected frame lists match the corresponding preparation manifests.
- Artifact scan: no private absolute paths, media paths, frame image data, API keys, or motion/performance fields were found in the pilot outputs.
- `git diff --check`: passed; staged changes will be checked again before commit.

## Changed files

- `backend/intelligence/evaluation/stage5_semantic.py`
- `backend/intelligence/evaluation/stage5/README.md`
- `backend/tests/test_stage5_semantic.py`
- `backend/intelligence/evaluation/stage5/pilot/{01,04,08,12}.selection.json`
- `backend/intelligence/evaluation/stage5/pilot/{01,04,08,12}.json`
- `backend/intelligence/evaluation/stage5/pilot/{01,04,08,12}.md`
- `V9_STAGE5_SEMANTIC_BASELINE_REPORT.md`
