# V9 live provider validation gate

Date: 14 October 2026. Exact candidate: `cbc70c0d8a1b6250d19cca8891cf106d0e1ab0d0`.

This is a read-only production-state investigation and a record of the live-provider gate. No product code, production service, production database, deployment, or tag was changed. The only CLI setting changed was selecting the sole Render workspace locally, as authorized by the user.

## Candidate verification

Local `v9`, this isolated worktree's base `HEAD`, and `git ls-remote --heads origin v9` all resolved to `cbc70c0d8a1b6250d19cca8891cf106d0e1ab0d0` before the investigation. The main checkout's unrelated uncommitted work was left untouched. This report is the only change on `codex/v9-live-provider-validation`.

## Production-state investigation

| Surface | Read-only finding | Evidence and limit |
| --- | --- | --- |
| Vercel Production | The active production alias `https://video-analyser-nu.vercel.app/` points to the ready deployment `video-analyser-64mrb4fj9-bressie10s-projects.vercel.app`. GitHub Production deployment record `7044373294` maps that deployment URL to commit `b7e085b89d412e189bcedf4c6c5d0e533f31651d`; its successful status was recorded at `2026-10-13T16:43:11Z`. This is **not** the final V9 candidate. | Authenticated `vercel inspect ... --json`, Vercel production deployment list, GitHub deployment/status API. The public alias returned HTTP 200 and HTML referencing `index-B_btP7Pu.css`; the CSS bytes and SHA-256 matched a fresh local build from `b7e085b`. This establishes public accessibility, not a measured user count. The production JS includes environment-dependent build content and was not byte-identical to the local build. |
| Render backend | The live Render service is on branch `v8` with automatic deployments off. Its current deployment `dep-db75u73l550s73asf620` is **live** at `b7e085b89d412e189bcedf4c6c5d0e533f31651d`, manually triggered `2026-10-13T16:41:00Z` and finished `16:42:39Z`. The prior live deployment was `4314123f7e4fdb62a1634000dc36958b150e66c4` from 4 October. Thus the backend did change in the same period as Vercel. | Authenticated `render services --output json` and `render deploys list ... --output json`. Public `/health` and `/health/db` returned 200, but those endpoints do not establish V9 readiness or schema version. Public OpenAPI exposes Stage 8.1 intelligence but no Stage 8.3 Creative Analysis detail/media routes, consistent with the older deployed commit. |
| Production migration 015 | **Unverified.** Migration 015 exists in the `b7e085b` source tree, but a source file is not proof that SQL was applied. `render postgres list --output json` returned zero managed databases in the selected workspace. No authorized read-only production PostgreSQL connection was available, so no production schema query was run. | `/health/db` only checks database connectivity; it cannot prove the `performance_observations` table, triggers, indexes, or RLS. The prior final audit applied migration 015 to a disposable local database only and explicitly recorded no intentional production migration. |

The deployed frontend and backend are both `b7e085b`, while local and remote `v9` are `cbc70c0`. No production-state mutation was made during this investigation.

## Owned test cohort and Creative Intelligence

The user confirmed that **no owned, authorized Meta test cohort is available**. No customer account or data was used. Consequently no connected test account, six distinct ads, six uniquely mapped analyzed videos, or exact reporting window could be established. No CTR Creative Intelligence request or real provider-media resolution was made.

| Required check | Result |
| --- | --- |
| Exact-context cohort selection and six distinct creatives | Not run; no qualifying owned cohort. |
| Six source-media resolutions and six matching previews | Not run. |
| Stage 7.2 findings, support citations, counterexamples, transcript/OCR/frame citations, and timing claims against source media | Not run. No finding can honestly be classified supported, questionable, or unsupported. |
| Stage 7.3 experiment grounding against observed differences | Not run. No hypothesis sanity judgment was made. |

The earlier database and fixture-based audit in `V9_FINAL_RELEASE_AUDIT.md` is not live Meta validation and is not an independent semantic accuracy result.

## Creative Analysis and degraded behavior

No real Meta-backed browser playback session was possible. Initial play, pause/resume, forward/back seek, repeated byte ranges, direct opening at a comparison citation, timeline synchronization, return to Intelligence without a rerun, and playback after provider re-resolution are **unverified live**. Scene boundaries and transcript/OCR timestamps were not compared with a real source video; there are no recorded discrepancies or confirmations.

The previous final audit recorded fixture/database checks for disconnected or unavailable provider media, stored evidence, missing modalities, and other degraded states. This task did not repeat those checks and cannot establish how an expired real connection or unavailable real media behaves in production. In particular, stored evidence remaining usable when playback fails is not live-provider verified.

## Real latency and resource measurements

| Requested measurement | Result |
| --- | --- |
| Intelligence total wall time; source-media resolution/download time | Unmeasured. |
| Stage 7.2 and Stage 7.3 latency; model call count; safe token counts | Unmeasured. |
| Creative Analysis media grant latency; video first byte/startup latency | Unmeasured. |
| Provider resolutions during play/seek; approximate bytes transferred | Unmeasured. |

No signed Meta URL, access token, customer identifier, model prompt, or raw model response was collected in this report. The existing per-request Meta media re-resolution behavior was left unchanged. There is no live evidence yet to judge its latency, reliability, or rate-limit impact or to justify a correction.

## Unresolved gates

1. Provide an owned, authorized exact-context six-ad/six-video cohort and perform the CTR evidence, hypothesis, playback, timeline, and measurement review described above. Until then, this document does not clear the real-provider release gate.
2. Obtain an authorized **read-only** production database path and check whether `performance_observations` and migration 015's constraints, indexes, triggers, and RLS actually exist. The Render CLI workspace has no managed PostgreSQL database listed. This production-schema question is separate from the locally completed database-backed audit.
3. Reconcile the intentional release plan with the already public `b7e085b` frontend/backend deployments before any further production change. This task did not deploy or tag anything.

D — no qualifying owned Meta test cohort was available
