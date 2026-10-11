# V9 semantic independent review package

## Scope

- Exact base: `1ad70ce841f2cd903d3e66674846c3352a854174`.
- Branch: `codex/v9-semantic-independent-review`, in an isolated worktree.
- Four pilot source IDs: `01`, `04`, `08`, and `12` only.
- This package makes no semantic inference or model call. It does not modify
  Stage 5–5.4 predictions, Stage 5.1 provisional truth, or existing comparison
  files. No remaining video was run.

## Reviewer-facing materials

Share only the [blind directory](backend/intelligence/evaluation/semantic_review_package/blind/)
and provide each complete source video with audio through a separate private
channel. The blind directory contains a guide generated from frozen ontology
`1.1.0`, the controlled primary structure roles, generic annotation and
timestamp instructions, and four blank JSON templates. It contains no
predictions, provisional truth, comparison values, source-specific expected
answers, model confidence, or adjudication notes.

The template captures provenance, category coverage, technique status and
confidence, timed evidence notes, physical CTA events and attached labels,
and a primary structure timeline. The validator rejects unknown ontology IDs,
invalid point/interval/whole-video timing, CTA labels outside events,
contradictory primary structure overlaps, and complete coverage claimed
without watching the full video. A reviewer who did not hear audio cannot
claim audio coverage. Independent adjudication intake requires a blind review
of the complete video with audio.

## Offline adjudication and comparison

The [workflow](backend/intelligence/evaluation/semantic_review_workflow.py)
validates reviewer JSON, compares any number of distinct reviewers pairwise,
and writes a separate adjudication draft without resolving disagreements.
Reports retain label presence, interval boundaries, whole-video formats,
CTA event grouping and labels, structure roles, and category coverage.
Finalization requires a manually filled resolved annotation, adjudicator
provenance and notes, unchanged original reviewer SHA-256 hashes, and a
separate output file. It records both total and human reviewer counts. Fewer
than two human reviewers are explicitly flagged; every reference carries
`gold_truth: false`.

The `compare-frozen` command opens and validates an adjudicated reference
before reading a Stage 5.4 candidate. It reports label P/R/F1, interval
agreement at ±0.25/±0.5/±1.0 seconds, structure agreement, format and CTA
disagreements, and unsupported/missed findings as separate measures.
Partial or unavailable coverage abstains. The workflow commands are in the
[package README](backend/intelligence/evaluation/semantic_review_package/README.md).

## Verification and limits

- Focused review and existing intelligence/Stage 5–5.4 tests: **69 passed**.
- Python compilation, privacy scan, and `git diff --check` passed.
- Blind package tests verify exact frozen definitions, blank templates, and
  absence of pilot prediction/truth leakage. Tests also verify unsupported IDs
  are rejected, original reviewer files remain immutable, two-reviewer
  disagreements survive, adjudication output is separate, and incomplete
  coverage abstains.
- No reviewer annotation, adjudicated reference, or post-adjudication candidate
  comparison exists yet. Human review quality and agreement cannot be
  measured until reviewers watch and annotate the source videos. No source
  video, extracted frame, audio file, or private absolute path was committed.
