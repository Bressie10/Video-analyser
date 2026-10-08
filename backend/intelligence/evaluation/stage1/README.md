# V9 Stage 1: real-media calibration pilot

This workflow measures the **existing V8** scene, OCR, ASR, motion, and metadata outputs. It does not infer semantic labels from them. Keep the private manifest, media, annotations, adjudication, low-level truth, and analysis results **outside the repository**. Use authorized media only; record provenance and any use limits in `rights_note`. Do not commit private paths or third-party clips. The CLI rejects private inputs/results inside this checkout.

**Order:** select media → independent semantic passes A/B → semantic agreement and adjudication → independent low-level passes A/B → low-level agreement and adjudication → reviewed low-level truth → run V8 → evaluate V8 against reviewed truth. Human truth **must be complete before annotators or reviewers see any V8 output**. Store V8 results in a separate private directory that is inaccessible during human annotation. This prevents detector-output anchoring.

## 1. Select 10–15 sources

Create a private directory such as `/private/tmp/cm-v9-pilot` and copy `pilot_manifest.example.json` there. Replace the one illustrative row with 10–15 real rows. `source_ref` is stable, unique, and filename-safe. `media_path` is an absolute local file path. `creator_ref` can be `null` if unknown. Set `group_ref` to the creator/campaign/source family so related clips share a partition; do not put one creator in more than three rows. Use at least five groups. Record `duration_seconds` from an independent inspection, not the pipeline output. `low_level_truth_available` means reviewed signal truth exists; change it only when it does. Split assignment stays fixed across semantic and low-level records.

Intentionally include talking head, tutorial, product demo, screen recording, interview, storytime, before/after, fast and slow editing; captions and no captions; music and no music; clean and noisy audio; simple and busy scenes; and weak, ordinary, and strong content. These are sampling tags, **not detector labels or claims of measured quality**. Prefer varied creators and ordinary clips over a polished-only set. Record near-duplicate exclusions in a private selection log. A 10–15 clip pilot can illustrate failures, not establish population accuracy.

```sh
cd backend
.venv/bin/python -m intelligence.evaluation.stage1 validate /private/tmp/cm-v9-pilot/manifest.json
```

Use the installed backend Python in this checkout, or another environment with `backend/requirements.txt` installed.

## 2. Two independent semantic annotation passes

Follow [`../README.md`](../README.md) guideline **1.1.0** and the frozen `Annotation` schema. Create a separate private `semantic/manifest.json` with the V8.5 shape (`sources` containing `reference_id`, `media_ref`, `notes`; `split_assignments` containing `source_ref`, `partition`, `group_ref`). Its source IDs, partitions, and groups must mirror the pilot manifest. Put first-pass files under `semantic/annotations/<source_ref>__a.json`, then give the same media and guideline to a second annotator who cannot see the first record; write `<source_ref>__b.json`. Each file must have a distinct pseudonymous `annotator_ref`, `annotation_ref`, timestamp, `guideline_version: "1.1.0"`, explicit coverage, and uncertainty in `notes` or span notes. Empty labels only mean a negative when that category has complete coverage. Validate each record with `Annotation.model_validate_json(...)` before sharing.

After both passes, run the agreement report and retain its JSON:

```sh
python -m intelligence.evaluation agreement /private/tmp/cm-v9-pilot/semantic > /private/tmp/cm-v9-pilot/agreement.json
```

Review differences using the media and both records. Write `reviewed/<source_ref>.md` from `adjudication.example.md`; cite both original annotation refs, each disputed label/time, the decision and its evidence, and unresolved uncertainty. Write `reviewed/<source_ref>.json` as a **third** frozen-schema `Annotation` with a separate reviewer pseudonym and matching source/guideline. Keep both independent JSON files unedited. The reviewed record is the final semantic truth; it does not belong in `semantic/annotations`, because agreement must compare the independent passes only.

```sh
python -m intelligence.evaluation.stage1 annotations /private/tmp/cm-v9-pilot/manifest.json \
  --semantic /private/tmp/cm-v9-pilot/semantic --reviewed /private/tmp/cm-v9-pilot/reviewed \
  > /private/tmp/cm-v9-pilot/annotation-audit.json
```

The audit requires two independent records per pilot source, consistent split/group/duration, and notes for every reviewed record. It reports coverage and agreement without replacing disagreements. `annotation_status` tracks progress in the private manifest; change to `reviewed` only after the third record and notes exist.

## 3. Two independent low-level passes and review

The Stage-1-local `low_level_truth_version: "1.0.0"` format is a private pilot record, **not** a frozen V8.5 or production schema. Copy `low_level_truth.example.json` into `low_level/annotations/<source_ref>__a.json` and `__b.json`. Give the same media to two different pseudonymous annotators. The second must not see the first record before completing their pass. Each record has `source_ref`, `record_kind: "independent"`, `annotator_ref`, timezone-aware `annotated_at`, explicit coverage for all five signals, optional notes, and signal-keyed `observations`. Preserve both files unchanged.

Use `coverage` for every signal: `complete`, `partial`, or `unavailable`. A complete empty list means an exhaustively checked negative. Partial/unavailable sections are excluded from agreement and scoring, even if draft observations exist. Record uncertainty in event `note` fields and in record `notes`. Neither annotator may copy a V8 output as truth.

- `scene_boundaries`: human **editorial boundaries** at first frame of the new shot/scene, with a note for a gradual transition. They are not automatically “cuts”; the V8 output field is named `cut_timestamp_seconds` for historical reasons. Compare at 0.1, 0.25, and 0.5 seconds; choose the primary tolerance before inspecting results.
- `ocr`: each visible text span has literal `text`, human `normalized_text`, `start_seconds`, `end_seconds`, optional region and note. Use one record per contiguous appearance; do not invent subframe timing.
- `transcript`: human text and timed segments. Add word timings only if independently annotated; this evaluator does not assume them. Mark silent media as complete with empty text and segments. Missing speech and hallucinated speech use segment overlap and remain approximate when segment boundaries differ.
- `motion`: only human-observable intervals mapping to V8 `camera_shake`, `camera_zoom`, `camera_pan`, `general_motion`, `local_motion`, or `unknown`. A visual zoom can come from subject motion or editing; record ambiguity in the note. Do not force a V8 type where the mapping is unclear: mark motion coverage partial and explain it.
- `metadata`: independently inspect `duration_seconds`, `video.resolution.width`, `video.resolution.height`, and `video.fps` when known. Supply a tolerance per value; leave unavailable fields out. `video.fps` is V8's average frame rate.

After both independent files are complete, run the low-level agreement audit **before running V8**. It compares scene events within a chosen time tolerance, OCR span overlap and normalized text, transcript text and any independently timed segments, motion overlap and type, and metadata values within declared tolerance. It preserves unmatched events and disagreements by signal; it produces no universal agreement score. Partial/unavailable coverage is shown as `not_compared`.

For metadata, a field present in only one pass is reported as missing from the other pass. When both supply a field, the comparison uses the larger of their declared tolerances and displays both original tolerances. A `complete` metadata section must include independently checked duration; add resolution and FPS where known.

Review both records against media. Write `low_level/reviewed/<source_ref>.md` using `low_level_adjudication.example.md`, documenting decisions and unresolved uncertainty. Write `low_level/reviewed/<source_ref>.json` with the same Stage-1-local format, `record_kind: "reviewed"`, a **separate** `reviewer_ref`, and timezone-aware `reviewed_at`; retain coverage, notes and reviewed observations. A reviewer may consult both independent records and the media, but must remain blind to V8 output. The audit requires both original files, a review time no earlier than either independent annotation, the reviewed record and nonempty adjudication notes whenever `low_level_truth_available` is true. Set that manifest field to true only after this review is complete.

```sh
python -m intelligence.evaluation.stage1 low-level-audit /private/tmp/cm-v9-pilot/manifest.json \
  --low-level /private/tmp/cm-v9-pilot/low_level --scene-tolerances 0.25 \
  > /private/tmp/cm-v9-pilot/low-level-agreement.json
```

This command needs only the manifest and human truth files. It never reads detector output. A complete pilot should have two independent records for **every** source before any reviewed record is accepted; missing or partial sources remain visible in the audit, while `low_level_truth_available: true` requires the full review gate.

## 4. Run existing V8 and evaluate

Run only **after semantic and low-level reviewed truth is finalized**. The runner calls `app.analysis_pipeline.analyze_file(..., allow_silent=True)` on private local files, using the existing normalizer, scene, OCR, optical-flow, and ASR path. It records the Git pipeline commit and SHA-256 input hash. Temporary normalized media is deleted after each clip. Existing result files are never overwritten. No production DB, route, worker, API, provider, or frontend is used.

```sh
python -m intelligence.evaluation.stage1 run /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results
python -m intelligence.evaluation.stage1 evaluate /private/tmp/cm-v9-pilot/manifest.json \
  --results /private/tmp/cm-v9-pilot/results --low-level /private/tmp/cm-v9-pilot/low_level \
  --scene-tolerances 0.1 0.25 0.5 \
  > /private/tmp/cm-v9-pilot/evaluation.json
```

The evaluator first runs the low-level truth audit and scores **only `low_level/reviewed/<source_ref>.json`**. It reports independent scene precision/recall/F1/timing and tolerance sensitivity; OCR exact normalized text precision/recall, text similarity, temporal IoU, and `unmatched_visible_text_span_rate`; transcript token error rate, timing for exactly aligned segment text, and missing/hallucinated **segment-presence** counts; motion presence/overlap and type confusion; and metadata correctness. `unmatched_visible_text_span_rate` means no OCR track had any positive temporal overlap with a visible truth span; a temporally paired track with incorrect text still counts as paired. Exact text recall separately measures correct recognition. Transcript missing/hallucinated segment counts measure temporal presence, **not** recognition correctness. `null` denominators are undefined, not zero accuracy. Partial/unavailable truth abstains. It never emits an overall analysis score. Keep source-level results for uncertainty intervals and examples; use group-level resampling or Wilson intervals for proportions when reporting small-sample estimates, and disclose the chosen method.

Review unmatched events and type confusion against media. Assign failure categories **only after observing an example**; record source/time, signal, evidence, category, and reviewer in a private failure log. Potential scene, OCR, ASR, and motion categories in the task brief are prompts for inspection, not prepopulated findings. Include no category without an observed case. Compare any generated-media fixtures separately from real footage.

## Decision gate

Fill `V9_STAGE1_CALIBRATION_REPORT.md` from the private evaluation and review logs. Report per-signal denominators, detector coverage, abstentions, uncertainty, example failures, and which derived features are reliable within this pilot. Choose the next detector/evidence improvement only after comparing the measured failure severity and coverage. If no real clips or independently reviewed truth are available, leave the gate open and do not invent a ranking.
