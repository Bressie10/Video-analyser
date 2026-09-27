# V4 Wave 1 integration handoff

## Delivery

- Branch: `codex/v4-wave1-integration`.
- Worktree: `/private/tmp/video-analyzer-v4-wave1-integration`.
- Base: local `v4` at `d5f86a24754ca2303b9a80f8f70381fd6f2f6d77`.
- Three cherry-picks, in requested order:

| Source | Integrated commit |
| --- | --- |
| `672ecf533c852803f8d24d18a0ad22141f8019af` | `7808920af21a8c84f908f23ad6cd212ef8b56e9b` |
| `01a20c2b47e178022da7e9ea67ddbe0f89786556` | `d5b9bea30218266942677d08a8b035449deb189e` |
| `a530f869c4d1f1bc94048f72dbf795b62c4738c2` | `b610641b83138af9c451b704c6c00bd9081304de` |

The subsequent commit containing this report is the separate integration/glue
commit, titled `Integrate V4 company state, management and backend contract`.
Nothing is pushed or merged into `v4`.

Conflicts occurred in `frontend/src/main.tsx` (provider/shell imports) and
`frontend/tests/company.test.mjs` (different add/add suites). Both provider and
shell were retained. State tests were preserved as `company-state.test.mjs`, UI
tests as `company.test.mjs`, with separate package scripts. `package.json`
auto-merged; script targets were reconciled as part of that conflict resolution.
All glue changes followed completion of the three picks.

## Backend ↔ frontend mappings

The backend commit and `backend/COMPANY_API.md` are authoritative. The company
adapter validates/projections supported fields; components do not fetch company
routes directly. All IDs below are internal UUIDs.

| Frontend adapter | Backend method/path | Body / wire result |
| --- | --- | --- |
| `listCompanies` | GET `/api/companies?include_archived=true` | `{companies: Company[]}` |
| `getCompany` | GET `/api/companies/{company_id}` | Company |
| `createCompany` | POST `/api/companies` | `{name}` → Company, 201 |
| `renameCompany` | PATCH `/api/companies/{company_id}` | `{name}` → Company |
| `archiveCompany` | POST `/api/companies/{company_id}/archive` | No body → Company |
| `restoreCompany` | POST `/api/companies/{company_id}/restore` | No body → Company |
| `listAvailableMetaAccounts` | GET `/api/meta/accounts` | `{accounts: AvailableAccount[]}` |
| `linkAccount` / `unlinkAccount` | PUT / DELETE `/api/companies/{company_id}/accounts/{account_id}` | No body → Company |
| `listAssignableAdsContent` | GET `/api/companies/{company_id}/accounts/{account_id}/ads` | `{ads: AssignableAd[]}` |
| `assignAdsContent` / `unassignAdsContent` | PUT / DELETE `/api/companies/{company_id}/ads/{ad_item_id}` | No body → `{ok:true}` |
| `reassignAdsContent` | POST `/api/companies/{company_id}/ads/{ad_item_id}/reassign` | `{target_company_id}` → `{ok:true}` |

Wire companies contain `company_id,name,archived,accounts`; account records contain
`account_id,platform,display_name`; available accounts add `organic_owner`; Ads
records contain `ad_item_id,display_name,assigned`. The adapter maps these to
frontend `id/name` fields and retains links/assignment flags. There is no invented
pagination, global ad picker, or client-side ownership bypass.

## Application behavior

One CompanyProvider owns active selection. `useCompanyUI` bridges that store and
the real adapter into the existing CompanyShell/selector/management components.
The selector remains in the shell in loading, error, empty and management states.
The shared Meta connection remains reachable without an active company.

Only `video-analyzer.active-company-id`, containing the normalized internal UUID,
is persisted. Startup validation must finish before scoped UI appears. Missing,
invalid, inaccessible and archived IDs never select a fallback. Network/server
load failures hide the scope and permit retry. Denied startup access clears the
UUID. Blocked browser storage is reported and falls back to session-local state.
Cross-tab synchronization is not implemented.

Creation requires only a name, uses the existing authenticated session, immediately
selects/persists the returned company, and shows setup/Skip for now. Zero accounts
is valid. Rename updates the selector. Archiving the active company clears its
selection and scope; restoring makes it selectable without selecting it.

Management inspection does not change the active workspace. Available account
refresh reads locally discovered accounts; OAuth/discovery remains connection-wide.
Facebook/Instagram links stay exclusive. Ads accounts may be shared, but linking
one does not show content or metrics. Only the backend's per-company assignable-ad
metadata is displayed. Assignment/unassignment and atomic reassignment are wired;
targets must be active and linked to the ad's account. Blocked Ads unlink and organic
ownership conflicts show actionable 409 messages without automatic fixes.

Registered unsaved edits/in-progress work require confirmation before switching.
Ordinary switching does not prompt. The create form consumes its own submitted
edits, but other registered work remains guarded. No generation UI was added.

Scope signals/version checks and keyed React boundaries cancel or ignore late
results and reset company-specific state. Management results additionally carry
inspection/scope/revision keys and a render-time company check. Ownership changes
invalidate only affected active scopes; global Meta state remains intact.

## Legacy view handling and Wave 2

The production company shell does not mount the old unscoped library, job polling,
processing or generation controls. It displays setup or an explicit forthcoming
company-content notice, without claiming that linked accounts prove content exists.
The existing V3 ownership readers are repository helpers, not company-library HTTP
routes. No new content route or migration was needed for the selected gated approach.

Wave 2 must expose minimal company-scoped reads through those ownership helpers,
wire the library/processing flows to the active scope, and integrate generation
with cancellation and guards before enabling them. Idea generation/history,
feedback/lifecycle/publication/profile-settings UI and V5 redesign remain outside
this work. Legacy regressions run through `tests/legacy.html`, excluded from the
production build and containing no company selector.

## Verification

All successful final runs have zero failures/skips/cancellations:

| Check | Result |
| --- | --- |
| Full backend, disposable PostgreSQL, media enabled | 278 passed |
| Company API standalone | 11 passed (also included in 278) |
| V3 ownership/profile/idea/release cases within full suite | 139 passed |
| Remaining existing backend regressions within full suite | 128 passed |
| Company state/adapter/React boundary | 22 passed |
| Company UI fixture | 11 passed |
| Existing legacy browser flow cases | 35 passed |
| Existing Meta status browser cases | 6 passed |
| Production company browser integration/fault scenarios | 12 passed |
| Preserved V2 real FastAPI/media/PostgreSQL browser flow | 1 passed |
| Typecheck / production build / whitespace check | Passed |

Frontend total: **87 distinct cases**, comprising 21 state/adapter unit cases and
66 browser cases (including 13 integration/fault-scenario cases). No lint runner is
configured. The 74-case state/UI/existing-browser run and focused final UI rerun
both passed; reruns are not counted twice.

Coverage includes all requested A–Y behaviors: startup/no fallback; actual backend
selector and UUID persistence; delayed A response after switching to B (plus
A→B→A store fencing); name-only creation/empty setup; rename/archive/restore;
organic ownership conflict; shared Ads accounts, assignment/unassignment,
reassignment, blocked/successful unlink; guarded/ordinary switching; keyboard;
320/600/1280px management and 320px assigned-Ads controls; safe response/UI fields;
and the real browser→FastAPI→PostgreSQL lifecycle. Startup HTTP/network errors are
injected intentionally. The core lifecycle has no route interception.

Backend command: `TEST_DATABASE_URL=postgresql://127.0.0.1:55447/wave1_tests RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 .venv/bin/python -m unittest discover -s tests`.
Frontend scripts: `test:company`, `test:companies`, `test:e2e`,
`test:company-integration`, `test:integration`, `typecheck`, `build`.
Integration scripts require the disposable `TEST_DATABASE_URL`.

An initial SQL_ASCII database caused byte/text failures; successful runs used UTF-8.
An initial UI locator became ambiguous after adding reassignment and was narrowed
to the checkbox. The privacy collector was corrected to inspect completed requests,
since intentionally aborted response bodies could stall the harness. These were
resolved before the reported final runs. No V3 migrations were changed.

## Assumptions, risks and untested boundaries

- The existing Meta session is required; no new authentication/membership system.
- Meta status/provider boundaries are controlled fixtures. Live OAuth, Meta account
  discovery, real provider permissions and live provider data are not verified.
- Creation has the existing non-idempotent POST contract. An ambiguous network
  failure after server commit may require reloading companies before retrying.
- Company/account/Ads management lists remain unpaginated, as defined by the API.
- The legacy library is intentionally unavailable in the production Wave 1 shell.
- No production deployment, push or merge was performed. Existing dependency
  deprecation/native-library warnings did not fail verification.

## Files changed

The final branch includes the backend API/repository/router and API tests from the
backend pick; provider/store/adapter and state tests from the state pick; and
selector/shell/management/guard/style/UI fixtures from the UI pick. Glue changes
update adapter types and routes, bootstrap and shared connection wiring, management
callbacks/errors/reassignment, guards and discovery fencing; retain separate test
suites; add real company integration fixtures; preserve legacy tests through their
own entrypoint; and update documentation. The exact tracked file manifest follows.

- `README.md`
- `V4_WAVE1_INTEGRATION.md`
- `backend/COMPANY_API.md`
- `backend/app/company_ownership_repository.py`
- `backend/app/company_routes.py`
- `backend/app/main.py`
- `backend/tests/company_browser_server.py`
- `backend/tests/frontend_integration_server.py`
- `backend/tests/test_company_api.py`
- `frontend/COMPANY_STATE.md`
- `frontend/COMPANY_UI_CONTRACT.md`
- `frontend/package.json`
- `frontend/src/CompanyManagement.tsx`
- `frontend/src/CompanySelector.tsx`
- `frontend/src/CompanyShell.tsx`
- `frontend/src/CompanySwitchGuard.tsx`
- `frontend/src/MetaConnection.tsx`
- `frontend/src/company/CompanyProvider.tsx`
- `frontend/src/company/companyApi.ts`
- `frontend/src/company/companyStore.ts`
- `frontend/src/company/useCompanyUI.ts`
- `frontend/src/companyUI.ts`
- `frontend/src/main.tsx`
- `frontend/src/style.css`
- `frontend/tests/company-integration.test.mjs`
- `frontend/tests/company-integration.vite.mjs`
- `frontend/tests/company-state.test.mjs`
- `frontend/tests/company.html`
- `frontend/tests/company.test.mjs`
- `frontend/tests/companyFixture.tsx`
- `frontend/tests/flow.test.mjs`
- `frontend/tests/integration.test.mjs`
- `frontend/tests/legacy.html`
- `frontend/tests/legacyFixture.tsx`
- `frontend/tests/meta-status.test.mjs`
