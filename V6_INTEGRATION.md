# ContentMetric V6 integration

This is the combined local release candidate. It is not a deployed release or proof
of live Supabase, Google, Meta, Render configuration, or email delivery. Production
must pass the deployment gates and smoke checks below before cutover.

## Sources and isolation

- Foundation: `46768e51cf366e324f35fb5545f78195db0add34`.
- Company authorization: `46d7c7afa89c53d803ca595a9e84461cdb4bad44` → `d6cc816`.
- Meta authorization: `09f01cab8db618bab47e40df58eabbc4fa017f3a` → `509ca9b`.
- Frontend authentication: `dc32c20b9d13512b53c6960f82175fea001f6dbf` → `bfec920`.
- Branch `codex/v6-integration`, worktree `/private/tmp/contentmetric-v6-integration`.

The worktree was created at the exact foundation, then cherry-picked in the order
above. No textual conflicts occurred. The main checkout's existing
`frontend/vite.config.ts` modification was left untouched. No push or merge.

Semantic reconciliation was necessary despite clean Git merges: the callback test
now checks that a JWT-authenticated Meta owner still gets 403 for an unclaimed
company (the original cookie-only case remains separately covered). Browser tests
now send real local ES256 JWTs through the real `/api/me/companies` route; the V5
cookie-only startup middleware was removed. Fixtures explicitly provide roles.

## Final architecture

Supabase user → verified asymmetric JWT → FastAPI `AuthenticatedUser` → company
membership → company resources. JWT signature, issuer, audience, expiration, role,
and UUID subject are validated. ES256/RS256 only; no unsigned, `none`, symmetric
fallback or request-supplied identity. Email is display information, never an
access key. `/api/me` lazily provisions safe profile data and exposes no raw claims
or credentials. Supabase owns password/email/Google authentication and PKCE.

Company membership, personally owned Meta connections, and account/ad assignments
are separate checks. Company membership permits ordinary product work without a
Meta session. Linking requires both company owner and personally owned connection.
Organic accounts remain exclusive to one company; Ads accounts may span companies,
but an ad has one assignment and reassignment requires owner access to both sides.
Shared creative analysis, frozen evidence, idempotency and generation rechecks remain.

## Frontend and Meta flow

All application requests use `apiFetch`: company, content, profile, generation,
ideas, publication, library, jobs, discovery and Meta status/connect requests.
The only direct production `fetch` calls are inside that helper. All `/api/` responses default to private/no-store caching without changing existing stricter headers. It rejects
non-same-origin/non-`/api/` destinations and redirects, gets the current SDK token,
and adds Bearer authorization without manually persisting or logging tokens.
Supabase's SDK separately handles its own Auth requests. No external URL receives
the application Bearer through this helper.

Application 401 shares a bounded refresh and retries reads once; mutations are not
automatically replayed. Failed refresh/second rejected read locks the workspace.
403 preserves sign-in and shows permission feedback; child 404 hiding is retained.
A provider-session 401 explicitly carries `X-ContentMetric-Auth: provider` and does
not refresh/sign out the Supabase user. This preserves existing reconnection UX
while distinguishing provider state from application identity.

Connect opens a blank popup synchronously, then sends authenticated
`GET /api/meta/connect?response_mode=json`. The backend binds opaque OAuth state to
the verified initiating user. The frontend validates the returned HTTPS Facebook
OAuth destination and navigates the popup. Callback consumes single-use state and
checks the state cookie; caller `user_id`/callback JWT cannot replace the owner.
The callback's existing JSON is acceptable within this popup flow: the opener reads
only its same-origin callback, closes the popup and probes authenticated status.
No new redirect environment variable/domain or OAuth redesign is needed. Directly
opening a callback URL still displays safe JSON. Popup blocking has a recovery state.
Use the Vercel-origin callback, not the Render origin, to preserve cookie binding.

After session resolution, accessible companies validate the saved UUID before
mounting private UI. Invalid/inaccessible/archived selections are cleared with no
fallback. Zero companies gives company creation; POST `{name}` atomically creates
an owner membership and disconnected company with no connection ID or Meta gate.
Role is added to every rich company summary/mutation response. Unknown/missing roles
fail closed in the UI. Members retain content, generation, ideas/edit/feedback/
lifecycle/publications and profile read/refresh. Configuration, account/ad management,
archive/restore and reassignment destinations are owner-only UI controls. Backend
checks remain authoritative. Members receive owner-help copy for missing accounts.

Logout/user change aborts application requests, clears the selected UUID and remounts
the entire private workspace, including drafts, selections, generated results,
settings and Meta UI. Failed sign-out stays locked. Foreign stale Meta cookies are
rejected; they never transfer provider ownership. Public legal routes render before
Supabase or workspace initialization; `/login`, `/signup`, `/forgot-password`, and
`/auth/callback` remain public. Other app routes require a resolved session.

## Route audit

The regression inventory requests every method/path in the generated OpenAPI
schema without credentials and requires 401 except the explicit public allowlist.

| Classification | Routes | Authorization |
| --- | --- | --- |
| PUBLIC | `/health`, `/health/db` | Minimal health only |
| PROVIDER CALLBACK | `/api/meta/callback`, `/api/tiktok/callback` | Browser-bound, expiring single-use state; initiating user bound server-side |
| AUTHENTICATED | `/api/me`, `/api/me/companies`, `/api/companies` | Verified JWT; safe profile/membership lists; creation owns new company |
| AUTHENTICATED | Company summary/configuration/archive/restore/accounts/ads/content/profiles | Membership; owner for administration; archived rules retained |
| AUTHENTICATED | `/api/meta/companies/{company_id}/...` ideas, generation, evidence, feedback, publications/options | Membership plus child/source scope; owner is not required for ordinary work |
| AUTHENTICATED | Meta connect/test/disconnect/library/jobs/sync/batches/recommendations/discovery | JWT and personally owned connection where applicable |
| AUTHENTICATED | Deprecated FB/IG/Ads metrics | Owned Meta connection AND owned upload; write rechecks ownership |
| AUTHENTICATED | `/api/photos`, `/api/videos`, stored analysis/recommendations | JWT; persisted uploads owned by JWT subject; foreign/legacy IDs hidden |
| AUTHENTICATED | TikTok connect/videos and upload metrics | JWT; provider state/session bound to initiating user |
| INTERNAL | Background workers, repositories | No independent HTTP endpoints; existing transaction/worker fencing |

FastAPI schema/docs endpoints remain public framework metadata, not application data.
No application data route is intentionally anonymous. Legacy upload and TikTok holes
were found during integration and closed; merely adding JWT to those routes would
not have fixed cross-user stored-video access or provider-cookie reuse.

## Migrations, legacy data and RLS

Migrations 001–011 are byte-for-byte unchanged. Migration
`012_upload_ownership.sql` adds nullable upload ownership and its index. It is needed
to preserve manual upload APIs without exposing every user's stored analysis to
other authenticated users. Owner profile and upload persist in the same transaction.
Legacy videos, NULL-owner connections and companies without memberships survive,
remain unclaimed and are inaccessible through user routes. Reconnecting an existing
legacy Meta identity returns conflict, never a claim. No first-signup migration.

Real PostgreSQL tests cover fresh 001–012 and populated V5 001–010 → 011–012 with
content, metrics, assignments, profiles and saved ideas preserved. Ordinary tests
connect as disposable `postgres` (superuser/BYPASSRLS). A separate test runs all
migrations as a NOSUPERUSER/NOBYPASSRLS table owner and verifies owner access. A
non-owner role with explicit SELECT/INSERT grants still sees zero auth-owned rows
and cannot insert: default-deny RLS remains enabled, with no permissive policies.

The main checkout's configured DATABASE_URL was checked read-only: it points to a
local database, uses a non-superuser/non-BYPASSRLS role, and has no V6 auth tables yet.
This is NOT Render/Supabase production-role verification. The production backend
must own the migrated tables or use a dedicated BYPASSRLS role with SQL privileges.
If a different role applies migrations, verify ownership/grants before starting V6.
Do not disable RLS. Verify anonymous/authenticated Data API roles cannot access app
schemas, or disable their Data API exposure. No real `.env` or live data was changed.

## Coherent environment contract and deployment gates

| Location | Variable | Requirement |
| --- | --- | --- |
| Backend | `DATABASE_URL` | PostgreSQL with migrations 001–012 and privileges above |
| Backend | `SUPABASE_URL` | HTTPS project origin, matching token issuer and frontend project |
| Backend | `SUPABASE_JWT_AUDIENCE` | `authenticated` by default |
| Frontend build | `VITE_SUPABASE_URL` | Same Supabase project origin |
| Frontend build | `VITE_SUPABASE_PUBLISHABLE_KEY` | Public `sb_publishable_...` key; never service-role/secret |
| Backend | `META_APP_ID`, `META_APP_SECRET`, `META_LOGIN_CONFIG_ID`, `META_GRAPH_API_VERSION` | Existing Meta business login contract |
| Backend | `META_REDIRECT_URI` | `https://video-analyser-nu.vercel.app/api/meta/callback` for current production |
| Backend | `META_TOKEN_ENCRYPTION_KEY` | Stable Fernet key; no rotation/real key added here |
| Backend | `OPENAI_API_KEY`, `OPENAI_MODEL` | Existing server-side generation contract |
| Backend | `META_WORKER_ENABLED`, `COMPANY_PROFILE_WORKER_ENABLED` | Existing background worker controls, distinct from API process count |
| Legacy backend | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` | Only when enabling legacy TikTok |

Examples contain placeholders only. Preserve the existing Vercel `/api/:path*` →
`https://video-analyser-1ek5.onrender.com/api/:path*` rewrite as the first rule.
Application calls stay at `https://video-analyser-nu.vercel.app/api/...`; no CORS
workaround or browser-to-Render URL was introduced. Configure Supabase email
confirmation, Google provider, and allowlisted `/auth/callback` and recovery callback.

Meta state remains process-local, single-use, browser-bound, 600-second expiry.
TikTok's legacy state now has the same expiry/single-use/user-binding constraints.
The checked-in README starts one uvicorn process; Compose defines PostgreSQL only.
There is no committed Render service/start configuration and no connected Render
control-plane access to prove the deployed process/instance count. Required start:

```sh
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
```

Require one Render instance as well (or independently verified process affinity).
Restarts during OAuth fail closed and require reconnect. No evidence here establishes
multi-process deployment, so a durable state store was not speculatively added.
**Production gate:** verify one process/instance and DB-role access before release;
if actual deployment requires multiple processes/instances without affinity, this
candidate must not ship until durable state storage is implemented and tested.

## Validation and remaining limitations

Final counts and commands are recorded below from one sequential validation invocation that exited 0. Tests
use local signed ES256 JWTs/JWKS, real PostgreSQL, deterministic Supabase HTTP/Google
PKCE and Meta/model fixtures; actual local FFmpeg/transcription/OCR/media tests run.
The complete product sequence is covered in complementary layers: SDK/browser auth
and logout tests; real browser→FastAPI→PostgreSQL company/idea/publication/profile
flows; and a sequential new-user API/database OAuth→content→idea→User B isolation
scenario. It is not a live-provider end-to-end run.

No new dependencies, billing, invitation/team UI, gamification, V7/V8 features or
V5 redesign. JWT revocation still follows expiry (bounded JWKS cache); local logout
is not immediate global token revocation. Browser PKCE recovery requires its verifier.
Provider/model availability and email delivery are outside deterministic evidence.

## Production smoke-test checklist

1. Back up; verify migration history; apply 011/012 only where pending. Verify legacy
   row preservation, default-deny RLS, app-role ownership and Data API restrictions.
2. Confirm the actual Render start command, one process/instance, stable encryption
   key, matching Supabase project/audience and asymmetric signing key configuration.
3. Confirm Vercel rewrites and all public legal/auth routes directly after refresh.
4. Sign up a new user; verify email delivery; login; confirm zero companies; create
   a company without Meta. Verify creator role and member versus owner controls.
5. Test Google PKCE and password recovery, including expired links. Inspect console.
6. Connect Meta through authenticated JSON initiation; confirm callback cookies and
   connection ownership, popup completion, discovery/linking and background sync.
7. Run content→generation→edit→feedback→lifecycle→publication→profile refresh.
8. Logout with requests/drafts in flight; login as another user; verify no stale UI,
   no cross-company/provider access, and no access to legacy UUIDs. Return to user A.
9. Exercise expired Supabase session, provider-only expiry, 403 and retries; check
   no loops, no tokens in logs, and 1440/1024/768/390/320px auth/account layouts.
10. Do not mark deployed readiness until live Supabase, Google, Meta, database-role
    and single-process deployment evidence is recorded separately.

## Reproducing the complete local validation

Normal setup installs backend requirements and frontend lockfile dependencies. The
validation worktree reused the existing backend virtualenv/frontend modules through
temporary symlinks and the already installed PyJWT package at
`/private/tmp/contentmetric-v6-jwt`; these links/artifacts are not committed.
Disposable PostgreSQL 17 listened on 127.0.0.1:55479.

Run the suites sequentially with native media thread counts bounded; an earlier
concurrent exploratory run hit a native-library shutdown abort after passing its
assertions and was rejected as release evidence. No test assertions were removed
to obtain a clean result. Real-browser fixtures use dedicated strict ports, and
auth/legal preview servers use OS-assigned ports. User-switch fixtures remove any
context-wide Authorization override so the application helper selects the JWT.

```sh
export TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55479/postgres
export RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
cd backend
PYTHONPATH=tests:/private/tmp/contentmetric-v6-jwt .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app tests
cd ../frontend
PYTHONPATH=/private/tmp/contentmetric-v6-jwt npm test
npm run typecheck
npm run build
cd ..
git diff --check
```

Browser plugin was unavailable; repository Playwright/Chromium ran at local Vite
origins (dynamic auth origin; real company 5284, media 5278, ideas 5288). Auth checks
cover login, signup, verification, forgot/reset password, callback failure, zero
companies and account controls at 1440, 1024, 768, 390 and 320px. Screenshots live
outside the checkout at `/tmp/v6-d-auth-screenshots`. Representative desktop/mobile
screenshots were visually inspected; automated checks cover every listed size.
Auth tests fail on unexpected console warnings/errors and unhandled page errors;
expected HTTP error responses used by negative tests are excluded from console
resource-error noise only. No lint script or Python lint/type checker is configured.
Existing native AV/FFmpeg duplicate-class and API deprecation warnings are recorded
in backend logs; they are not browser console warnings.

## Integration-only file manifest

The three source commits retain their own handoff manifests. The additional changes
are the following focused auth/ownership/UI/fixture/docs files:

```text
.env.example
DATABASE.md
README.md
V6_INTEGRATION.md
backend/app/company_routes.py
backend/app/facebook_routes.py
backend/app/instagram_routes.py
backend/app/main.py
backend/app/meta_ads_routes.py
backend/app/meta_auth_dependencies.py
backend/app/meta_discovery.py
backend/app/meta_library_routes.py
backend/app/tiktok.py
backend/app/video_repository.py
backend/migrations/012_upload_ownership.sql
backend/tests/company_browser_server.py
backend/tests/integration_auth.py
backend/tests/test_auth_database.py
backend/tests/test_company_api.py
backend/tests/test_company_ownership.py
backend/tests/test_facebook_api.py
backend/tests/test_facebook_database.py
backend/tests/test_instagram_api.py
backend/tests/test_instagram_database.py
backend/tests/test_meta_ads_api.py
backend/tests/test_meta_ads_database.py
backend/tests/test_meta_library.py
backend/tests/test_performance_database.py
backend/tests/test_recommendations_api.py
backend/tests/test_tiktok_api.py
backend/tests/test_v6_company_authorization.py
backend/tests/test_v6_integration.py
frontend/.env.example
frontend/src/CompanyManagement.tsx
frontend/src/CompanyShell.tsx
frontend/src/MetaConnection.tsx
frontend/src/auth/apiFetch.ts
frontend/src/auth/metaAuthorization.ts
frontend/src/company/companyApi.ts
frontend/src/company/useCompanyUI.ts
frontend/src/companyUI.ts
frontend/src/generation/GenerateIdea.tsx
frontend/src/main.tsx
frontend/src/shell/WorkspaceOverview.tsx
frontend/tests/auth.test.mjs
frontend/tests/authenticated.vite.mjs
frontend/tests/company-integration.test.mjs
frontend/tests/company-integration.vite.mjs
frontend/tests/company-state.test.mjs
frontend/tests/companyFixture.tsx
frontend/tests/content-settings.test.mjs
frontend/tests/flow.test.mjs
frontend/tests/foundation.test.mjs
frontend/tests/generation.test.mjs
frontend/tests/ideas.test.mjs
frontend/tests/integration.test.mjs
frontend/tests/integration.vite.mjs
frontend/tests/overview-content.test.mjs
frontend/tests/settings-v5.test.mjs
frontend/tests/wave2-integration.test.mjs
frontend/tests/wave2-integration.vite.mjs
```

## Final validation record (2026-09-27)

One sequential complete validation invocation exited **0**:

| Check | Result |
| --- | --- |
| Complete backend suite | **354 passed, 0 failures/errors, 0 skips**, 59.751s; process exited 0 |
| Complete frontend suite | **268 passed, 0 failures, 0 cancelled, 0 skips**, 179.345s |
| PostgreSQL | Real PostgreSQL 17; fresh 001–012 and populated V5→V6 upgrade; table-owner/default-deny RLS tests passed |
| Media/provider | Real local media preprocessing/transcription/OCR/analysis; deterministic Meta/model integration passed |
| Route inventory | 54 application operations require JWT; 2 health + 2 state-protected callback operations |
| TypeScript / production bundle | `npm run typecheck` and `npm run build` passed |
| Python compilation / whitespace | `compileall` and `git diff --check` passed |
| Browser console | No unexplained auth warnings/errors, unhandled rejections or framework overlays; negative HTTP cases intentionally exercised |
| Responsive auth | All listed auth/account/no-company states checked at 1440/1024/768/390/320px; representative screenshots visually reviewed |
| Logout/user switch | Deep draft/result/selection reset and abort tests; real JWT→API→DB User A→B→A browser test passed |
| Live providers/deployment | Supabase, Google, Meta, email delivery and deployed application **not tested** |

Evidence: `/private/tmp/v6-backend-final.log`, `/private/tmp/v6-frontend-final.log`,
`/private/tmp/v6-typecheck.log`, `/private/tmp/v6-build.log`; local orchestration
`/private/tmp/v6-final-validation.sh`. Final evidence is not assembled from isolated
test reruns. No source code changed after that complete run; this record and removal
of temporary symlinks/test artifacts completed the handoff.

The security audit found and closed anonymous legacy routes/upload IDOR, provider
401/app-session conflation, anonymous Meta initiation, missing member UI controls,
and obsolete browser JWT fixtures. No unresolved local authorization bypass was
identified. Deployment remains gated on actual production role/process verification
and live provider smoke tests, as described above.
