# V9 independent semantic review workflow

This offline workflow uses frozen ontology `1.1.0` and source IDs `01`, `04`,
`08`, and `12`. It performs no inference or model calls. Give reviewers **only**
the [blind directory](blind/) and access to their assigned complete source
videos with audio through a separate private channel. Do not give them this
repository, prior candidate files, provisional review, comparisons, or
adjudication files before they submit their annotation.

The blind directory contains the exact ontology definitions, controlled
structure roles, generic instructions, and one blank JSON template per video.
Copy a template for each reviewer; use distinct reviewer IDs and filenames.
Fill every `null` in the template, then add observations, CTA events and
labels, and primary structure intervals. Keep original submitted reviewer
files immutable. Two independent human reviewers per video are preferred.
The tooling records the actual reviewer count and human reviewer count if only
one independent human is available; it never substitutes an automated review
for a second human.

Run commands from `backend/` with the project's Python environment. Use
private paths outside this repository for submitted reviews, adjudication,
references, and comparison results. The examples use placeholders only:

```sh
python -m intelligence.evaluation.semantic_review_workflow validate REVIEW_A.json
python -m intelligence.evaluation.semantic_review_workflow validate REVIEW_B.json
python -m intelligence.evaluation.semantic_review_workflow prepare-adjudication \
  --reviews REVIEW_A.json REVIEW_B.json --output ADJUDICATION_DRAFT.json
```

The draft reports category coverage, label presence, interval boundaries,
whole-video formats, CTA event grouping and labels, and primary structure
differences. It does **not** resolve them. An adjudicator watches the full
source video with audio, reviews the original records, and fills
`adjudicator`, `resolution_notes`, and `resolved_annotation` in a **copy** of
the draft. The resolved annotation must be complete and explicit; the tool
does not copy either review as a default. Then run:

```sh
python -m intelligence.evaluation.semantic_review_workflow finalize-adjudication \
  --template COMPLETED_ADJUDICATION.json \
  --reviews REVIEW_A.json REVIEW_B.json --output REFERENCE.json
```

The tool checks original reviewer SHA-256 hashes and preserved disagreements,
then writes a separate adjudicated reference. With one reviewer, pass only one
file to both commands; the resulting reference explicitly records the limited
human review. No output is called gold truth. Partial and unavailable
categories abstain from later scoring.

Only **after** `REFERENCE.json` exists and validates, compare it with the
frozen Stage 5.4 candidate for the same source:

```sh
python -m intelligence.evaluation.semantic_review_workflow compare-frozen \
  --reference REFERENCE.json \
  --candidate intelligence/evaluation/stage5_4/candidates/01.json \
  --output COMPARISON.json
```

Repeat separately for `04`, `08`, and `12`. The comparison reports label
precision/recall/F1, interval agreement at ±0.25/±0.5/±1.0 seconds, structure
agreement, format disagreements, CTA event and label disagreements, and
unsupported/missed findings. It does not compute one overall semantic score.
The comparison output is separate from both inputs.

To regenerate the shareable materials from the frozen ontology without
reading any candidate or review data, use `make-blind-package --output-dir`
with a new empty directory. The tool creates only the guide and four blank
templates.
