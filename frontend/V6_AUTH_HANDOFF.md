# V6 frontend authentication handoff

Foundation: `46768e51cf366e324f35fb5545f78195db0add34`. Branch:
`codex/v6-auth-frontend`. No production configuration or backend business logic changed.

## Browser configuration and identity

Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` at build time, as shown
in `frontend/.env.example`. Only `sb_publishable_` browser keys are accepted.
Never supply service-role/secret keys. Missing configuration fails closed with a
sign-in configuration notice; public legal pages still render without network calls.
Enable email confirmation and Google in Supabase and allow the deployment's
`/auth/callback` and `/auth/callback?recovery=1` redirect URLs. Domain/provider
configuration is deliberately not modified here. Password minimum is 8 characters;
Supabase can enforce stronger requirements. Signup does not collect company details.

`src/auth/authClient.ts` is the only Supabase client module. It lazily creates the
SDK with PKCE, supported session persistence and automatic refresh. It only uses
`client.auth`; no browser database queries or manually managed access tokens.
`AuthProvider.tsx` subscribes synchronously to auth events and retrieves initial
session state without calling asynchronous SDK methods inside auth event callbacks.
Recovery is accepted only after the SDK's PASSWORD_RECOVERY event, not a query flag.
The SDK processes/exchanges callback credentials; the callback removes query/hash
credentials from browser history after resolution. PKCE links need the original
browser's verifier; an expired link or another browser shows a new-link prompt.

Public routes: `/login`, `/signup`, `/forgot-password`, `/auth/callback`, `/privacy`,
`/terms`, `/data-deletion`. Explicit Vercel rewrites preserve `/api` precedence and
the existing backend destination. Legal content is unchanged and resolves before
AuthProvider, company providers or Supabase initialization. Auth forms reuse V5
controls, spacing, colors and focus styling. Account email and sign-out live in
the app sidebar (mobile navigation disclosure).

## API and workspace lifetime

`src/auth/apiFetch.ts` handles every frontend application fetch. It retrieves the
current SDK session, adds Bearer auth only to same-origin `/api/` requests, rejects
redirects, preserves bodies/headers/idempotency keys/caller cancellation, and
combines cancellation with a session lifetime signal. A 401 shares one in-flight
refresh. Reads may retry once; mutations never automatically replay. A failed
refresh or a second rejected read locks/unmounts the workspace and signs out.
A successfully refreshed mutation still returns its original 401 so the existing
operation can offer an explicit retry with its existing idempotency key. A 403 is
passed to the feature's authorization handling and never logs out the user.

AuthGate mounts no company UI while identity or accessible-company validation is
pending. It gets `/api/me/companies` and validates the saved company UUID before
mounting CompanyProvider. The existing rich `/api/companies?include_archived=true`
list/store then retains V5's archived-management behavior and no-silent-fallback
rule. Stored selection is a preference, never authority. No-company users reach
existing company creation without needing Meta.

Identity changes key/remount the entire workspace, clearing content, generation
results, selected ideas, unsaved edits, settings and company caches. Logout clears
the selected UUID, cancels all application requests and unmounts private UI before
awaiting SDK local sign-out. On failure it stays locked with a retry, rather than
restoring private UI. Harmless global preferences remain. Local sign-out means this
browser, not revocation of all other devices or of already issued JWTs.

## Integration with B and C

B: retain the existing rich company wire shape and mutation responses; authorize
all endpoints independently. `/api/me/companies` is Agent A's startup contract.
Company creation already sends `{name}` with Bearer auth and has no Meta gate.
No application-table access, onboarding or billing is added.

C: Meta OAuth is separate from Supabase `/auth/callback`. `MetaConnection` accepts
an optional `beginAuthorization(signal): Promise<string>` adapter. It opens a blank
popup synchronously, awaits the authenticated adapter, then navigates to the returned
HTTPS authorization URL, retaining cancellation, popup completion and status probes.
Wire this prop from `main.tsx` with `apiFetch` after C's exact initiation route/method/
response is agreed. No final contract is invented here. Until integration the default
is the V5 `/api/meta/connect` popup navigation, which cannot carry Bearer auth and
**must be replaced for the V6 Meta cutover**. Do not put tokens in popup URLs.
All other Meta fetches now use apiFetch.

## Tests and evidence

`npm run test:auth` exercises the real SDK with deterministic intercepted Auth HTTP
responses, including PKCE, verification-required signup, Google initiation, recovery,
restoration, Bearer headers, 401/403, cross-user clearing, keyboard controls and
1440/1024/768/390/320px layouts. No live Supabase account is needed.

Existing V5 tests use `tests/authenticated.vite.mjs` and `authMock.ts`, test-only
module aliases that are absent from production Vite configuration. Legacy real
FastAPI/PostgreSQL fixtures still use their existing Meta cookie identity; a test-only
middleware derives their startup accessible list from that backend list. Those runs
verify V5 application regressions with the new request helper, not B/C's future V6
backend authorization. Two backend fixture scripts now accept FRONTEND_E2E_PORT to
avoid concurrent-agent port collisions; no backend routes/security code is changed.

Full suite: from frontend, provide backend/.venv with foundation dependencies and
TEST_DATABASE_URL for disposable PostgreSQL, then `npm test`, `npm run typecheck`,
`npm run build`, and `git diff --check`. No lint script is configured. Browser plugin
was unavailable; the existing Playwright installation was used. Review screenshots
are outside the repository under `/tmp/v6-d-auth-screenshots`.

Live email delivery, Google consent, real Supabase configuration, deployed redirects
and integrated B/C authorization remain untested. Configure and verify these before
release. Supabase reference: https://supabase.com/docs/reference/javascript/auth-resetpasswordforemail
and https://supabase.com/docs/reference/javascript/auth-onauthstatechange.

## Change manifest

```text
backend/tests/company_browser_server.py
backend/tests/wave2_browser_server.py
frontend/.env.example
frontend/V6_AUTH_HANDOFF.md
frontend/package-lock.json
frontend/package.json
frontend/src/MetaConnection.tsx
frontend/src/auth/AuthGate.tsx
frontend/src/auth/AuthPages.tsx
frontend/src/auth/AuthProvider.tsx
frontend/src/auth/apiFetch.ts
frontend/src/auth/auth.css
frontend/src/auth/authClient.ts
frontend/src/company/ProfileRefresh.tsx
frontend/src/company/companyApi.ts
frontend/src/content/contentApi.ts
frontend/src/generation/generationApi.ts
frontend/src/ideas/ideaApi.ts
frontend/src/main.tsx
frontend/src/metaLibrary.ts
frontend/src/shell/AppShell.tsx
frontend/src/vite-env.d.ts
frontend/tests/auth.test.mjs
frontend/tests/authMock.ts
frontend/tests/authenticated.vite.mjs
frontend/tests/company-integration.test.mjs
frontend/tests/company-integration.vite.mjs
frontend/tests/company-state.test.mjs
frontend/tests/company.test.mjs
frontend/tests/content-settings.test.mjs
frontend/tests/flow.test.mjs
frontend/tests/foundation.test.mjs
frontend/tests/generation.test.mjs
frontend/tests/ideas-api.test.mjs
frontend/tests/ideas.test.mjs
frontend/tests/integration.test.mjs
frontend/tests/integration.vite.mjs
frontend/tests/legal.test.mjs
frontend/tests/meta-status.test.mjs
frontend/tests/overview-content.test.mjs
frontend/tests/settings-v5.test.mjs
frontend/tests/wave2-integration.test.mjs
frontend/tests/wave2-integration.vite.mjs
frontend/vercel.json
```

## Final validation record

One complete final frontend run passed **260 tests, 0 failures, 0 skips** in
173.503 seconds, including 36 new auth cases and the real legacy FastAPI/media/
PostgreSQL browser integrations. Typecheck, production build and `git diff --check`
passed immediately after that same complete run. No final result relies on combining
isolated reruns. Existing native media-library and Starlette deprecation warnings
remain. No lint command is configured.

Validation used the existing main-checkout backend virtualenv via a temporary
worktree symlink, the foundation's PyJWT module at `/private/tmp/contentmetric-v6-jwt`,
and an isolated PostgreSQL 17 database on localhost:55471. The temporary virtualenv
symlink was removed after validation; normal setup must install backend requirements.
Final logs: `/tmp/v6-d-final-tests.log`, `/tmp/v6-d-final-typecheck.log`,
`/tmp/v6-d-final-build.log`, `/tmp/v6-d-final-diff-check.log`.

Chromium on local Vite verified login/signup/forgot/reset at 1440, 1024, 768, 390
and 320px, no document overflow, visible keyboard focus, labelled fields, Enter
submission, associated errors, accessible Google action and loading announcements.
Screenshots were inspected at desktop and 320px; framework overlays and unexpected
browser errors were absent in auth tests. Public legal production-bundle tests
passed independently without Supabase or backend access. These results do not
establish live-provider or integrated B/C release readiness.
