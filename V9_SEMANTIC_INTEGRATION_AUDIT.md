# V9 semantic foundation — integration and final audit

## Identity and ancestry

- V9 base: `5711f90283e44333f232af7e94c6cb4af06adba1`.
- Audited head and exact branch base: `9689c7380a6691c7ed3526dc9931bafff2095c01`.
- Audit branch: `codex/v9-semantic-integration-audit`.
- The audited head descends directly from the V9 base through 23 commits. No experimental branch was merged into this audit branch. This audit ran no semantic inference and made no change to frozen prompts, ontology, selection, ledger, validation, thresholds, CTA logic, or structure rules.

## Changed-file and production-boundary audit

The complete, path-by-path inventory of all **133** files changed from V9 base through audited head is in [V9_SEMANTIC_INTEGRATION_FILE_INVENTORY.txt](V9_SEMANTIC_INTEGRATION_FILE_INVENTORY.txt): 119 `backend/intelligence/evaluation/` files, seven evaluation tests in `backend/tests/`, and seven root research reports. These are all offline or research-only. Production files changed in this ancestry: **none** in `backend/app/`, `backend/migrations/`, `frontend/`, or the production intelligence normalization/schema modules. This report and inventory are the only new files on the audit branch.

The production analysis path has no Stage 5.4 import or invocation. The production recommendation API uses `app.recommendations`; structured idea generation uses `app.idea_generation`, which inherits the recommendation prompt, and `app.idea_service` captures only the existing stored analysis fields and performance snapshots. No Stage 5 ontology technique, candidate, report, ledger, or validator is supplied to those paths. No Stage 5 semantic technique is used in performance-linked reasoning, recommendations, or idea generation. The pre-existing prompts can compare observable transcript, scene, and OCR patterns with appropriately qualified metrics; this is not a connection to Stage 5 semantic findings.

The legacy motion gate remains in both downstream model calls: `without_motion_events` recursively removes `motion_events` before either recommendation or idea evidence is serialized. Stored and API analysis contracts retain their previous fields. Rejected Stage 5.4 drafts have no production import or downstream consumer. The only accepted candidate output is returned after `validate_synthesis` and the frozen `validate_draft` succeed; scale-out records `ValueError` validation failures in explicit `.failure.json` artifacts and writes no `.json` candidate for the rejected source.

## Frozen semantic contract

Low-level content evidence → deterministic frame selection → atomic, description-only evidence ledger → ontology synthesis → frozen validation → accepted report or explicit abstention/failure. The Stage 5 input is an allowlist of video metadata, transcript, OCR, and scene observations; performance, motion, reviewed truth, company history, and prior recommendations are excluded. Selected frames carry actual decoded timestamps and JPEG hashes. Ledger items cite supplied evidence and bounded intervals. Synthesis cites ledger IDs; the validators reject unsupported evidence gaps, incompatible primary structure roles, invalid ontology/timing/CTA claims, and performance claims. No partial semantic report is usable when validation fails.

Stage 5.4 is a frozen **offline, provisional, provenance-bearing, fail-closed candidate generator**. Its passing artifacts are contract-valid model interpretations, not independently verified facts.

## Narrow runtime fixes

Commit `699c4c6d0e2a6421b36c2f0c3c031a04b1487524` changed only the shared offline semantic runtime and focused tests for two scale-out defects:

1. The performance-claim guard accepts grammatical visual wording such as “shares the image”; it still rejects a shares count, engagement, conversions, and other explicit performance claims. The focused test exercises both acceptance and rejection.
2. Frame extraction clamps the requested frame index to `frame_count - 1` when container/audio duration exceeds video-frame duration. It records the timestamp of the decoded frame, preserving frame provenance. The focused generated-video test requests a final frame past the video stream and checks its actual timestamp.

Neither fix changes frame selection policy, ontology, prompt, ledger or synthesis validation. The saved `06` response was revalidated without regeneration. `09` remains rejected after extraction succeeds.

## Artifact and pilot audit

The committed [corpus audit](backend/intelligence/evaluation/stage5_4/corpus_audit.json) records eight accepted sources: **01 03 04 05 06 08 10 12**. All eight pass its ledger and contract checks, with zero ledger-support failures. Sources **07 09 11** remain explicit rejections: `07` and `11` cross unsupported ledger gaps; `09` assigns one atomic item incompatible primary roles. Their complete model checkpoints and `.failure.json` records remain research provenance. None has an accepted candidate `.json`; no rejected model output was repaired or regenerated for this audit.

The tracked-file audit found no committed source video, extracted frame, audio file, API key, credential material, embedded media payload, or private absolute media path. Candidate files hold provenance, selected-frame hashes/timestamps, ledgers, synthesis, and accepted reports; rejection checkpoints remain offline research artifacts. Example `/private/tmp` working directories in evaluation instructions are local command examples, not media paths or committed media.

## Regression results

| Check | Result |
| --- | --- |
| Stage 1–5/intelligence, recommendation, motion-gate and idea-focused tests | 209 run; 136 passed, 73 DB-gated skips; no failures |
| Backend non-DB suite (all discovered tests except `test_v6_integration`, which directly requires `TEST_DATABASE_URL`) | 530 run; 250 passed, 280 DB-gated skips; no failures |
| Unfiltered backend discovery with missing `TEST_DATABASE_URL` | 538 run; eight environment errors in `test_v6_integration`, 280 skips; no assertion failures |
| Python compilation (`app`, `intelligence`, `tests`) | Passed |
| Tracked media and credential/privacy scan | Passed; no private media or secret finding |
| `git diff --check` | Passed |

The existing checkout Python environment initially lacked the declared `PyJWT` dependency. It was installed to disposable `/private/tmp` storage for the rerun; no dependency or repository file changed. `TEST_DATABASE_URL` was unset. A disposable PostgreSQL cluster could not initialize because this host could not allocate its shared-memory segment, including on an unrestricted retry. Database tests are **environment-gated and unverified**, not application test failures. No migration or production query changed in this ancestry. No frontend build or browser check was needed because no frontend file changed.

## Unresolved limits and use gate

No independent human semantic validation exists. Stage 5.1 reference work was AI-assisted, non-blind, and provisional; no population semantic accuracy is known. Contract validity on 8/11 pilot sources does not establish semantic correctness or generalize to other videos. Sparse frames, OCR/transcript errors, and evidence gaps remain material; `07`, `09`, and `11` must abstain. Semantic outputs must not yet drive performance conclusions or causal recommendations. Human review and the DB suite remain outstanding validation gates for later production use; neither requires another semantic tuning stage.

**A — ready to integrate into v9 as provisional semantic foundation**
