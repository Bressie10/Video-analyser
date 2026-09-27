# V4 final release audit — 2026-09-27

Branch: `codex/v4-final-audit`, based on integrated `v4` commit
`32edaf2`. No push or merge. The release-audit commit contains this report;
its exact hash is in the completion message and `git log -1`.

**Verdict: READY to merge into v4 after the fixes below.**
No new product features, redesign, dependencies, speculative indexes, or migration
011. Migrations 001–010 and V3 authorization, persistence, refresh fencing and
invalidation architecture remain unchanged.

## Reproduced defects and minimal fixes

1. **Profile refresh never reported background progress or failure.** The original
   control stopped at “requested.” A new browser regression failed waiting for
   queued status. `ProfileRefresh.tsx` now reads the existing metadata-only profile
   list after a refresh request, displays queued/running/completed/failed states,
   and stops polling on completion, failure or unmount/company change. A failed
   status read has a read-only retry; uncertain POST retries retain their key.
   Raw worker/provider errors are never rendered. A completed but stale profile
   is explicitly distinguished from fresh intelligence. The action stays under
   company settings. Existing V3 workers and endpoints are unchanged.
2. **Publication options could leak a sibling company's ad label.** A directly
   owned organic post can also be another company's ad creative. Discovery can
   overwrite its legacy label with that ad's name. The old picker projected this
   label, despite content browsing already suppressing it. A real PostgreSQL/API
   regression returned `Sibling campaign private` before the fix. The picker now
   projects a neutral `Published post` label and never selects raw labels or Meta
   IDs. The regression covers both existing and removed creative edges, since
   edge removal does not clean historical labels.
3. **Publication dates were discarded by the picker adapter.** Neutral-label posts
   on one platform were indistinguishable even when published on different dates.
   An adapter regression returned `undefined` for the provided timestamp. The
   adapter now retains and validates `published_at`; the picker renders it as a
   timestamp. Historical associations still do not dereference live content.

Changed files:

- `backend/app/company_ownership_repository.py`: safe publication projection.
- `backend/tests/test_v4_idea_api.py`: sibling-label privacy regression.
- `backend/tests/wave2_browser_server.py`: unassigned account/content fixtures and
  real profile worker with an offline generator.
- `backend/IDEA_API.md`: corrected publication-label contract.
- `frontend/src/company/ProfileRefresh.tsx`: scoped refresh status tracking.
- `frontend/src/ideas/ideaApi.ts`, `IdeasPage.tsx`: preserve/display publication date.
- `frontend/tests/content-settings.test.mjs`: refresh progression, failure, retry,
  and late-response regression coverage.
- `frontend/tests/ideas-api.test.mjs`: publication-date adapter assertion.
- `frontend/tests/wave2-integration.test.mjs`: expanded integrated release flow.
- `V4_FINAL_AUDIT.md`: this report.

## Integrated acceptance evidence

| Area | Verified behavior and evidence |
| --- | --- |
| Company context | Store tests validate UUID-only persistence, startup validation, clearing archived/foreign IDs, no fallback, scope resets and A→B→A races. Browser tests check persistent shell context, guards for unsaved edits/generation and late responses even when transport abort is ignored. |
| Management | Real company API and browser tests cover name-only create with immediate activation, rename, archive clearing, restore without selection, exclusive organic accounts, shared Ads accounts, assignments, unassignment/reassignment, blocked Ads unlink and archived mutation rejection. |
| Content | `test_company_content_api.py` checks SQL ownership before pagination, sibling exclusion, content-only shared creatives, current analysis, deterministic dates/UUID ordering, null dates, search/platform/type/date filters, archived/foreign/auth failures. Mounted V4 browsing/source requests use only `/api/companies/{id}/content`. Global preview/sync/preparation remain gated. |
| Sources | Browser/adapter and real API tests cover exactly latest 20 of 25, all 7, safe zero, manual 1–20, nullable/different analysis UUIDs, library UUID requests, reset on company switch. No performance auto-ranking. |
| Generation | Real company recommendations route, explicit sources/targets, optional brief, linked target defaults, duplicates/retries and one persisted structured idea. V3 integration tests verify the model runs outside the capture transaction and final source/session/company/profile revalidation fences persistence. |
| History | Company scope, search/status/feedback/target/date filters before cursor pagination, inaccessible cursors/details, stale responses, empty/failure states; ordinary UI never requests frozen evidence. |
| Editing | Explicit Edit/Save/Cancel, no autosave, server-value restore, dirty switch guard, only title/concept/script edited. Evidence stays immutable. Simultaneous clients remain last-write-wins. |
| Feedback/lifecycle | None/like/dislike with optional reason, clearing removes reason, archived rejection and unchanged evidence. Draft/used/published/discarded are reversible organizational states; discard does not delete. |
| Publications | Scoped picker and PUT/DELETE, multiple/duplicate links, foreign rejection, sibling creative rules, historical links surviving ownership changes without granting live access, safe unavailable history. Privacy regression additionally covers contaminated owned-organic labels. UI describes manual associations, not matching, posting or causal attribution. |
| Profiles | Active-company settings action uses shared refresh endpoint. New browser tests cover queued/running/success/failure, network retry and late A responses; real stack processes refresh through the existing worker with offline generation. V3 fencing/invalidation tests remain green. |
| Security/failures | V4 company/content/idea tests exercise 401/404/409 and response allowlists. No raw Meta IDs, provider secrets/private URLs or sibling metrics in scoped content/picker projections. Network and archived failures retain safe/error states; no unscoped data is relabeled as company data. |
| Functional UI | Keyboard labels, focus, dialog behavior, disabled/loading states, management, generation, history and picker covered by browser tests at 320/600/1280px. Screenshots inspected; no redesign. |
| Migrations | Separate empty-schema run applied exactly 001→010 and verified the composite refresh profile/job FK. Full suite retains populated V2→V3 ownership, populated 008→009 evidence preservation and populated 009→010 valid/invalid upgrade tests. |

Expanded real-stack path:

Create company → automatically active → link Facebook/Instagram accounts → browse
company content → latest 20 of 25 → generate one persisted idea → history → edit and
Save → Like → Dislike with reason → Like clears reason → used status → link two
publications → unlink one → reload persisted idea → refresh company intelligence
through a real worker → success → switch B → no A results → reload → B restored.
Independent tests cover rapid late-response switching, management/Ads operations,
invalid persistence and archived-company mutation failure. Meta/OpenAI are
controlled offline boundaries; routes, sessions, worker, SQL and persistence are real.

## Final verification

Disposable PostgreSQL 17, UTF-8, port 55443. Tests create/drop isolated schemas or
databases. No application/production database is used.

| Check | Result |
| --- | --- |
| Full backend including generated/offline media | 294 passed |
| Frontend unit/adapter | 32 passed |
| Browser with controlled HTTP fixtures | 111 passed |
| Real-stack/offline browser E2E | 15 passed |
| All browser tests (including real stack) | 126 passed |
| Total frontend | 158 passed |
| Typecheck / production build / whitespace | Passed |
| Fresh migrations 001–010 | Passed |
| Populated V2/V3 upgrade regressions | Passed |
| Final failures / skips | 0 / 0 |
| Configured lint | No frontend or backend lint configuration exists |

Commands (from the indicated package):

```sh
# backend
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55443/postgres RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -s tests
# frontend
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55443/postgres HF_HUB_OFFLINE=1 node --test --test-concurrency=1 tests/*.test.mjs
npm run typecheck
npm run build
git diff --check
```

Audit logs: `/tmp/v4-audit-backend-final.log`,
`/tmp/v4-audit-frontend-final.log`, `/tmp/v4-audit-migrations.log`.
Initial sandbox runs could not bind/connect to localhost; authorized reruns passed.
The three intentional pre-fix regressions failed as described above. Existing
Starlette/httpx, PySceneDetect and macOS media-library warnings are non-fatal.

## Risks, assumptions and untested boundaries

- Live Meta OAuth, permissions, actual media/insights, live OpenAI output quality,
  deployment, production credentials and production data were not tested.
- Profile processing requires `COMPANY_PROFILE_WORKER_ENABLED=true`; a disabled
  worker leaves work queued. Status tracking lasts while the settings component
  is mounted. Worker processing continues independently after navigating away.
- Simultaneous idea edits are last-write-wins. Pagination is a live view, not a
  multi-request snapshot. Manual source mode loads all analyzed pages.
- Generation retry keys live in the mounted workflow; reloading or confirming a
  switch loses the local key. A cancelled wait may still save an old-company idea;
  stale responses cannot render it under the newly selected company.
- Safe generic post labels intentionally sacrifice descriptive names; the picker
  distinguishes by platform/time. Posts with identical timestamps remain hard
  to distinguish without future safe content metadata or preview support.
- Company-safe media preview, sync and preparation remain gated as required.
  Historical links do not establish current availability or causal performance.
- No migration 011, architecture change, new auth model, publishing, ranking,
  redesign or visual-polish work is included. V5 remains separate.
