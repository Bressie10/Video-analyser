# V9 low-level integration release candidate

Branch: `codex/v9-low-level-integration`. Base: V8.5 intelligence foundations `07ad7a92a67f39fca5bf7d7f9687de0355cd09ff` (`v9`). The validated commits form one linear ancestry; this branch starts at the final research tip `9a66273c31de39fcbc40704462ec25913e3fee2b`, so no experimental branch was merged and no commit was duplicated. This report is the integration commit. Nothing was merged into `v9`, deployed, or tagged.

## Integrated provenance

| Scope | Commit |
| --- | --- |
| Stage 1 pilot workflow | `4321052c573a8b0308fb934263aca0ac3541500f` |
| Stage 1 reviewed-truth gate | `ee029eda5d747fe44a72fc184cd2e413178cf505` |
| Stage 2 production OCR | `6cfbe673feb76e13a03c98f61533aa16c1cfcbad` |
| OCR evaluator | `6a93eb8767fdc0d46a90fae0580c6275f79c069a` |
| Stage 3 threshold sweep | `6365d3e9718c2a534821e92e343cfcd72e1b77ae` |
| Stage 3.1 scene audit | `19d6d3608ea9679dc04c994c4bced50cdafc4fa7` |
| Stage 3.2 repaired scene reference | `635992bcb15b3f81e5df2b8e337c50e620a3cbea` |
| Stage 4 stabilization | `70844d5d350c65fdac67f1a02e6d6991ce5ade89` |
| Stage 4.1 quality audit | `8df2284cd56ead551ea38b3c8a71db6d9669b576` |
| Stage 4.2 scene-aware replay | `3feb309ea08d598a0cc9e543deb95b66f7b56d09` |
| Stage 4.3 evidence contract | `9a66273c31de39fcbc40704462ec25913e3fee2b` |

## Production and research state

Production changes since V8.5 are confined to `backend/app/video_processing.py`: Stage 2 keeps raw OCR observations during sampling and consolidates adjacent detections into the existing `on_screen_text` shape, with fuzzy-text, movement, confidence, and one-frame safeguards. Scene detection still calls `ContentDetector` with threshold `27.0`. Production motion detection, its public event schema, the frozen V8.5 intelligence schemas, and frontend are byte-unchanged from the base. No Stage 4 code is imported by production routes or prompts.

The Stage 1, Stage 3–3.2, and Stage 4–4.3 tools, tests, and derived reports are offline evaluation infrastructure. The OCR evaluator adds normalized word-occurrence precision, recall, F1, and temporal coverage while retaining historical `exact_text` and `exact_text_and_time` scores. Partial or unavailable low-level truth abstains. Stage 3.2 commits a scene-only reference repair; private pilot media, frames, full annotations, and results remain outside Git.

Rejected production experiments: threshold `36`, Stage 4 stabilization and scene reset variants, and the Stage 4.3 simplified motion contract. The current research direction is `motion_present` with conservative `local_motion`; numeric flow descriptors are observations, not camera-technique interpretations. `camera_pan`, `camera_zoom`, `camera_shake`, and `general_motion` are not trusted semantic signals. Motion should not be used as trusted downstream semantic evidence until independently validated.

## Provisional calibration observations

The user-supplied repaired OCR pilot comparison is normalized F1 about `0.496 → 0.530`, precision `0.340 → 0.375`, recall `0.914 → 0.905`, and predicted normalized tokens `1974 → 1771`. These are provisional pilot comparisons, not population estimates or a new tuning target.

The Stage 3.2 scene reference was originally Gemini-assisted and user-reviewed; scene boundaries for 04, 07, and 09 were repaired from user-supplied full-video annotations. The reviewer had seen detector-related material. This is provisional, non-blinded, **not gold human truth** and not population accuracy. At ±0.5 s, threshold 27 changes from F1 `0.500` under the earlier incomplete reference to `0.725` under the repaired one; threshold 36 scores `0.731` on the repaired reference, a small sample-specific difference that does not change the production decision. Stage 4.1 uses one AI visual review without independent human adjudication. Stage 4.3's selected 54-event audit supports further research, not production accuracy claims.

## Audit and limits

- The source diff from V8.5 changes only production OCR; scene, motion, frozen schemas, database migrations, recommendation code, and frontend have no source diff. No experimental semantic claim was added to an LLM prompt.
- Existing V8 recommendation and idea paths still send legacy `motion_events` and invite comparison of motion. This predates these commits. Prompt-level exclusion of legacy semantic motion is **not verified**; address it before treating downstream motion reasoning as trusted. No Stage 4 experimental output is sent there.
- No video, extracted frame, audio, or image asset is tracked at this tip. Derived JSON and Markdown contain observations and provenance; some reports reference private paths or frame filenames, but do not contain the media.
- Stage 3.2 notes a pre-existing source 08 OCR truth interval past manifest duration. It was outside the scene-only repair. Rights for the private pilot media were not independently verified for redistribution.

## Validation

Focused Stage 1/3/4 tests: 47 passed. OCR consolidation: 8 passed. Intelligence contracts/evaluation: 21 passed. Recommendation API: 14 passed. Python `compileall` and imports for the API, OCR, and evaluation modules passed. `git diff --check 07ad7a9..HEAD` passed; run a final working-tree check after this report is added.

The full backend discovery with a disposable copy of the declared PyJWT dependency ran 486 tests: 8 errors were unguarded V6 integration cases requiring `TEST_DATABASE_URL`, and 280 tests were skipped for unavailable database infrastructure. Excluding only those 8 cases, the full suite that can run without PostgreSQL passed: 478 tests, 280 skips, zero failures/errors. No `TEST_DATABASE_URL` was supplied. A disposable PostgreSQL cluster could not be initialized because the host returned `could not create shared memory segment: No space left on device`, including outside the sandbox. Database integration and a fresh real-media end-to-end analysis were therefore not rerun in this integration worktree; their absence is an environment/evidence limit, not a demonstrated code failure. No live provider, deployed service, or frontend browser flow was tested.

## Exact files changed from V8.5

Production: `backend/app/video_processing.py`.

Stage 1 and OCR evaluation: `V9_STAGE1_CALIBRATION_REPORT.md`, `backend/intelligence/evaluation/stage1.py`, `backend/intelligence/evaluation/stage1/README.md`, `backend/intelligence/evaluation/stage1/adjudication.example.md`, `backend/intelligence/evaluation/stage1/low_level_adjudication.example.md`, `backend/intelligence/evaluation/stage1/low_level_truth.example.json`, `backend/intelligence/evaluation/stage1/pilot_manifest.example.json`, `backend/intelligence/evaluation/stage1_truth.py`, `backend/tests/test_ocr_consolidation.py`, `backend/tests/test_stage1_calibration.py`, `backend/tests/test_stage1_ocr_evaluation.py`.

Scene evaluation: `backend/intelligence/evaluation/stage3/scene_fp_audit.json`, `backend/intelligence/evaluation/stage3/scene_fp_audit.md`, `backend/intelligence/evaluation/stage3/scene_threshold_sweep.json`, `backend/intelligence/evaluation/stage3/scene_threshold_sweep.md`, `backend/intelligence/evaluation/stage3/scene_truth_stage3_2.json`, `backend/intelligence/evaluation/stage3_1_audit.py`, `backend/intelligence/evaluation/stage3_1_frames.py`, `backend/intelligence/evaluation/stage3_2/scene_threshold_sweep.json`, `backend/intelligence/evaluation/stage3_2/scene_threshold_sweep.md`, `backend/intelligence/evaluation/stage3_2_report.py`, `backend/intelligence/evaluation/stage3_2_scene_truth.py`, `backend/intelligence/evaluation/stage3_scene.py`, `backend/tests/test_stage3_1_scene_fp_audit.py`, `backend/tests/test_stage3_2_report.py`, `backend/tests/test_stage3_2_scene_truth.py`, `backend/tests/test_stage3_scene.py`.

Motion research: `backend/intelligence/evaluation/stage4/motion_stabilization.json`, `backend/intelligence/evaluation/stage4/motion_stabilization.md`, `backend/intelligence/evaluation/stage4_1/motion_classification_audit.json`, `backend/intelligence/evaluation/stage4_1/motion_classification_audit.md`, `backend/intelligence/evaluation/stage4_2/scene_aware_motion.json`, `backend/intelligence/evaluation/stage4_2/scene_aware_motion.md`, `backend/intelligence/evaluation/stage4_2_motion.py`, `backend/intelligence/evaluation/stage4_3/motion_contract_experiment.json`, `backend/intelligence/evaluation/stage4_3/motion_contract_experiment.md`, `backend/intelligence/evaluation/stage4_3_motion.py`, `backend/intelligence/evaluation/stage4_motion.py`, `backend/tests/test_stage4_1_motion_audit.py`, `backend/tests/test_stage4_2_motion.py`, `backend/tests/test_stage4_3_motion.py`, `backend/tests/test_stage4_motion.py`.

Integration documentation: `V9_LOW_LEVEL_INTEGRATION_REPORT.md`.

## Next V9 stage

Collect independently reviewed, detector-blind low-level truth with explicit complete/partial coverage; repair OCR and scene reference omissions; validate motion presence and locality on a broader, rights-cleared set. Gate downstream semantic use of existing motion events before considering a production motion contract change.
