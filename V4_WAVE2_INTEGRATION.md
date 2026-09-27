# V4 Wave 2 integration

Integrated on `codex/v4-wave2-integration`. No push and no merge into `v4`.
The integration/glue commit is separate from all four cherry-picks; its hash is
reported in the delivery message (`git log -1` after completion).

## Commit provenance and conflicts

| Source | Integrated cherry-pick |
| --- | --- |
| `841670d5c98526ea1413f109bf03ee07992f720a` Content API | `54812cc5df007434ece0735fbc2696acb836eb0d` |
| `8f45e00763aebddc390149d0eccccb9b278fe2e6` Idea API | `7569e2405e9084efb4767a7ad40df23df349405a` |
| `c9e060943d3d6405a2a3e92be6417e56524403e9` Generation UI | `2abc9ada6639c7cecc69e185529043220f85f921` |
| `007642bad28be698576ca05a21caca04606c153a` Ideas UI | `aba6a3f59764548140436b9fe1ed691632c78534` |

Applied backend before frontend. README conflict retained both API descriptions.
Frontend package conflict retained both generation and ideas scripts. Shell conflict
combined the setup render callback with unlinked-company history support; main
mounted both generation and history. No style/fixture merge conflicts occurred;
subsequent adapter and fixture corrections belong to the separate glue commit.

## Frontend to backend mapping

`company_id` always comes from the validated active CompanyProvider scope.
`I` below means `/api/meta/companies/{company_id}`.

| UI | Endpoint and wire behavior |
| --- | --- |
| Content library | `GET /api/companies/{company_id}/content` with `limit=20`, `offset`, `order=desc`, optional nonblank `search`, `platform`, `analyzed_only`; `{items,next_offset}` |
| Default generation sources | Same endpoint, exactly `analyzed_only=true&limit=20&order=desc`, first page only |
| Manual generation sources | Same analyzed query, follow `next_offset`, select 1–20 library UUIDs |
| Generate | `POST I/recommendations`: `{request_id,video_ids,generation_brief,target_platforms}`; one saved idea |
| History | `GET I/ideas`: `limit=25`, optional `after`, `search`, `status`, `feedback`, `target_platform`, `created_from`, `created_to`; `{items,next_cursor}` |
| Detail | `GET I/ideas/{idea_id}`; safe allowlist of title, concept, script, targets, lifecycle, feedback, publications, timestamps and optional brief |
| Save / lifecycle | `PATCH I/ideas/{idea_id}`: `{title,concept,script}` or `{status}` |
| Feedback | `PUT I/ideas/{idea_id}/feedback`: `{feedback,reason}`; reason only retained for disliked |
| Publication picker | `GET I/publication-options?limit=25[&after=UUID]`; maps `id`/`label`, with no unsupported search |
| Associations | `PUT` / `DELETE I/ideas/{idea_id}/publications/{library_item_id}`; bodyless |
| Profile refresh | `POST /api/companies/{company_id}/profiles/shared/refresh`, `Idempotency-Key` header; 202 is a queued refresh |

The UI reads associations from full idea responses; the separate GET publications
route remains available and is backend-tested. Evidence GET exists but is never
requested by ordinary UI. History date controls use UTC start-of-day inclusive and
next-day exclusive bounds. History/company filtering occurs in SQL before limits.

## Behavior

- Generation's misleading `video_ids` field contains **library_item_id**, never
  nullable/different `video_id`. Explicit tests exercise both null and different IDs.
  Twenty-five analyzed rows resolve to 20; seven resolve to seven; zero disables
  generation with setup guidance. Manual mode allows 1–20 eligible explicit IDs.
- Linked Instagram/Facebook targets start checked; none selected blocks submission.
  Meta Ads is never a target. Brief is optional. Loading locks duplicate submits;
  success displays structured persisted output on the same page and refreshes history.
  Unchanged uncertain retries reuse a UUID; successful/changed attempts use new UUIDs.
- The Wave 1 global gate is replaced by safe company content browsing with search,
  platform/readiness filters and pagination. Only unsupported media preview, sync
  and preparation/analysis controls stay unavailable. No unscoped library route is
  mounted in the active-company app; legacy components remain for V2 regression tests.
- History/detail remain available for active unlinked companies. Editing is explicit
  Edit/Save, with Cancel restoring the last server state and errors retaining drafts.
  No autosave, fake revision tokens or migration. Concurrent clients are last-write-wins.
- Feedback supports Like, Dislike with/without reason and clearing to none. All four
  lifecycle states are reversible; discard is visually separated.
- Publication selection uses currently scoped options, supports multiple links and
  unlinking, and does not publish or attribute performance. Historical UUID/date-only
  associations use neutral text and unverified availability; they do not fetch or
  authorize live metadata/metrics. Inaccessible historical links remain removable.
- Scope boundaries clear prior-company sources, results, history, edits and picker
  state immediately. Requests combine scope/lifetime cancellation and late-response
  guards. Generation and unsaved edits register the existing switch guard, including
  while management is open. Unrelated shell/Meta state remains intact.
- Archived/inaccessible mutation errors use actionable safe messages. Backend remains
  authoritative; archived companies deny generation, mutations and reads.
- Existing V3 shared-profile refresh is now a secondary Manage companies action for
  the active company, labelled with its name and showing loading/queued/error states.
  Refresh retries preserve the key until success. The UI does not claim job completion.

## Verification

Disposable PostgreSQL: local port 55442, UTF-8; fixtures migrate and drop isolated
schemas. OpenAI/Meta boundaries are offline/mocked, with real session authorization,
FastAPI, SQL, ownership and persistence in database-backed tests.

| Check | Result |
| --- | --- |
| Full backend, including media integration | **293 passed, 0 skipped, 0 failed** |
| Frontend unit/adapter checks | **32 passed** |
| Browser checks with controlled HTTP fixtures | **108 passed** |
| Browser → real FastAPI → PostgreSQL | **15 passed** (12 Wave 1, 1 legacy media, 2 new Wave 2) |
| All browser checks | **123 passed** (includes the 15 above) |
| Total frontend checks | **155 passed, 0 skipped, 0 failed** |
| TypeScript, production build, diff whitespace | Passed |
| Configured lint | Neither frontend nor backend has a lint command/configuration |

Commands, from the appropriate package:

```sh
# backend
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55442/postgres RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -s tests
# frontend
node --test tests/generation.test.mjs tests/ideas-api.test.mjs tests/ideas.test.mjs tests/content-settings.test.mjs
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55442/postgres node --test tests/company-state.test.mjs tests/company.test.mjs tests/company-integration.test.mjs tests/flow.test.mjs tests/meta-status.test.mjs tests/integration.test.mjs
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55442/postgres npm run test:wave2-integration
npm run typecheck
npm run build
```

Backend discovery includes content API, V4 idea API, company ownership/profiles,
persistent ideas, feedback/publications, company API and V2 recommendation regressions.
Media checks use generated known samples and cached OCR/Whisper models. Browser
checks include 320/600/1280px overflow and keyboard/focus checks; generated mobile
screenshots were visually inspected.

Acceptance coverage:

| Requested checks | Evidence |
| --- | --- |
| A, AC: company content isolation / no global library | `test_company_content_api.py`, `content-settings.test.mjs`, real Wave 2 browser flow |
| B–K: latest 20, fewer, manual IDs, null video IDs, empty, targets, saved output, duplicates | `generation.test.mjs`, `test_v4_idea_api.py`, real Wave 2 flow |
| L–N: generation guard and scope races | `generation.test.mjs` deliberately ignores transport abort; `content-settings.test.mjs` covers late library response |
| O–P: scoped history, all filters and cursor pagination | `ideas.test.mjs`, `test_v4_idea_api.py` |
| Q–S: Edit/Save, Cancel, unsaved guard | `ideas.test.mjs`, real Wave 2 flow |
| T–W: feedback variants and reversible lifecycle | `ideas.test.mjs`, backend idea/feedback suites |
| X–Z: scoped options, multiple links and unlink | backend picker tests, `ideas-api.test.mjs`, `ideas.test.mjs`, real Wave 2 flow |
| AA: unavailable historical association | backend live-revocation tests, UI historical-link tests, real neutral-association rendering |
| AB: archived mutation | backend rejects every mutation; new browser archive/save test preserves the draft and stored data |
| AD: complete real stack | `wave2-integration.test.mjs`: choose A → browse → model-stub generation → history → edit/save → like/used → two links → unlink → reload → refresh → switch B; shutdown verifies database row and one model call |

Initial sandbox-only runs could not bind/connect; authorized reruns passed. Initial
real-stack run exposed empty `search=` returning 422; the glue omits blank search,
and the final real-stack run passes. Initial backend run skipped 3 opt-in media
checks; final media-enabled run passed all 293. Non-fatal existing dependency
warnings (Starlette/httpx, PySceneDetect and duplicate AVFoundation classes) remain.

## Files in the glue commit

- `frontend/src/company/CompanyContent.tsx`, `ProfileRefresh.tsx`: scoped browsing/settings action.
- `frontend/src/main.tsx`, `CompanyShell.tsx`, `style.css`: both workflows, history refresh, settings slot and existing control styling.
- `frontend/src/generation/{GenerateIdea.tsx,generationApi.ts}`: source contract, IDs, pagination and saved-history notification.
- `frontend/src/ideas/{IdeasPage.tsx,ideaApi.ts}`: exact picker contract, UTC date bounds, history refresh and safe errors.
- `frontend/tests/{generation,ideas-api,ideas,content-settings,wave2-integration}.test.mjs`, `wave2-integration.vite.mjs`, `frontend/package.json`: reconciled fixtures and repeatable checks.
- `backend/tests/wave2_browser_server.py`: real stack fixture with offline model.
- `README.md`, frontend generation/ideas contracts and this report: current behavior and evidence.

## Risks, assumptions and remaining work

No remaining work in the requested Wave 2 integration scope. No dependencies or
speculative migrations were added. Production assumes a configured backend model
and existing Meta session; live Meta/OpenAI, deployment and production data were
not tested. Profile enqueue is verified; live intelligence refresh completion is
not claimed. Existing worker/profile suites test processing with offline boundaries.

Known limitations / small future V4 work:

- Company-safe preview/media, sync and preparation controls need scoped capabilities;
  their legacy global versions remain unavailable. Library titles intentionally use
  safe generic labels; no provider thumbnails are exposed.
- Manual generation currently loads all analyzed offset pages before local filtering;
  large libraries may benefit from incremental server-side picker filtering later.
- Request keys are retained within the mounted generation workflow; reload/confirmed
  company switch discards them. A cancelled wait may still persist an old-company idea.
- Multi-client editing remains last-write-wins; cursor/offset pages are live views,
  so concurrent mutations can change membership. No speculative concurrency layer.
- Historical association availability is unverified, not proof of current access;
  current picker/PUT authorization is separate. The picker supports pagination but
  no search because the real backend does not provide it.
