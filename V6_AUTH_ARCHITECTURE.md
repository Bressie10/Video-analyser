# ContentMetric V6 authentication foundation

This commit is Agent A's foundation, not the public-use authorization cutover.
Agents B/C must retrofit the existing company/resource and provider routes before
V6 is released. No production settings, domains, provider configuration or data
were changed. V5 Meta-cookie endpoints deliberately retain their current behavior.

## Identity and trust boundary

Supabase Auth owns credentials, email verification, email/password sign-in,
forgot/reset password and Google sign-in. Do not create local passwords or another
identity provider. Agent D uses `@supabase/supabase-js` for authentication only.
React sends its access token as `Authorization: Bearer <token>` to FastAPI;
application-table queries and business logic remain behind FastAPI.

`app/auth.py` validates signatures with PyJWT and the configured project's
`/auth/v1/.well-known/jwks.json`. ES256 and RS256 only; no `none`, HS256 fallback,
shared signing secret, unverified payload identity or token-selected key URL.
`SUPABASE_URL` must be an HTTPS project origin; issuer is exactly that origin plus
`/auth/v1`. `SUPABASE_JWT_AUDIENCE` defaults to `authenticated`. Required claims:
`exp`, `iat`, `iss`, `aud`, `sub`, `role`; expiry, issue time and optional `nbf`
are checked. Role must be `authenticated`, anonymous Supabase sign-ins are rejected,
and `sub` must parse as a UUID. No token/raw claims are returned or logged.

PyJWT[crypto]>=2.10,<3 is the only added dependency: maintained JWT/JWK parsing,
claim validation, signature verification and bounded JWKS caching. Existing
`cryptography>=44,<47` remains the cryptographic dependency constraint. The JWKS
set cache lasts 300 seconds, refreshes on an unknown key ID, and has a five-second
HTTP timeout. Individual signing keys are not cached indefinitely. Key revocation
can lag by the cache duration (plus Supabase's upstream cache); logout/account
revocation does not invalidate an already issued JWT immediately. Short provider
access-token lifetimes are needed; no live session-revocation check is implemented.
Existing HS256 projects must switch to asymmetric signing before these routes work.

`AuthenticatedUser` is an immutable dataclass with `user_id: UUID` and optional
signed `email`. Email is display information only, not proof of verification or an
authorization key. Never trust user-editable `user_metadata.email_verified`.
Email verification is enforced by Supabase Auth configuration, not inferred here.
User IDs in body/query/custom headers and Meta cookies cannot override JWT identity.

References: [Supabase JWTs](https://supabase.com/docs/guides/auth/jwts),
[signing keys](https://supabase.com/docs/guides/auth/signing-keys),
[claims](https://supabase.com/docs/guides/auth/jwt-fields).

## Migration 011 and identity persistence

Apply `backend/migrations/011_auth_foundation.sql` once after 001–010. It uses
BEGIN/COMMIT and is not idempotent. Back up and verify migration history first.

- `user_profiles`: Supabase user UUID primary key, optional display name, created
  and updated timestamps. No credentials, email copies or provider secrets.
- `company_memberships`: primary key `(company_id,user_id)`, role `owner|member`,
  created timestamp; restrictive FKs to companies/profiles. The user-leading index
  supports accessible-company listing and profile-reference checks.
- `companies.connection_id` becomes nullable. Existing connection FK, composite
  unique key and dependent company-account/ad FKs remain. A company without a
  connection cannot link accounts with a nonmatching connection. Connecting a
  company later must be explicit and authorized; do not null an existing linked
  connection or infer one from browser state.
- `meta_connections.owner_user_id`: nullable FK to profiles, indexed when non-null.

Profiles use a **logical external reference** to Supabase Auth's UUID, not a physical
FK to `auth.users`: this application also runs on standalone PostgreSQL, including
all existing test fixtures. Only trusted backend operations provision profiles from
verified `sub`. This does not duplicate Supabase identity/credential storage.
Account deletion/reconciliation with Supabase is future work; a profile row alone
is never authentication. Future metadata updates must set `updated_at` explicitly.

No backfill, fake users, first-user claim, email inference, UUID rewrites, company
duplication or legacy deletion occurs. Old companies may have zero memberships and
old connections retain NULL owners. They are invisible through the new user-scoped
API until an explicit separately authorized admin migration assigns ownership.
V5 cookie access remains transitional and must be replaced by Agents B/C.

## Repository and authorization contracts

`auth_repository.create_company_for_user(db, verified_user_id, name)` creates the
profile if needed, a disconnected company, and its creator's owner membership in
one transaction/savepoint. Failure rolls back all three, even when the outer
caller catches the failure. It joins an existing transaction without committing
unrelated work. Agent B must route new application company creation through it.
Legacy creation and raw administrative SQL can still create unclaimed companies;
the schema intentionally cannot globally require an owner while preserving V5.

`list_accessible_companies` joins memberships to companies using only the verified
user UUID. It projects safe fields and role, excludes archived companies by default,
and supports `include_archived=True` for management. Users may have multiple
companies; companies may have multiple owners/members. No invitation/team UI exists.

`require_company_access(db,user_id,company_id)` checks membership and active company.
`require_company_role(...,role='owner')` requires the exact role. Both reject
missing/foreign/unclaimed/archived companies by default; archived access requires
an explicit server-side `include_archived=True` for management/restore operations.
They raise `CompanyAccessDenied`, never infer access through a connection.
`FOR SHARE` locks company and membership until transaction end. Call them inside
the **same non-autocommit transaction** as the protected operation. For concurrent
mutations, acquire company write locks first in a consistent order to avoid lock
upgrades. Recheck access before persistence after slow external/model calls.

`auth_dependencies.py` supplies FastAPI wrappers. Use
`Depends(require_authenticated_user)`, `Depends(require_company_access)` or
`Depends(require_company_role('owner'))` and `Depends(authenticated_database)`.
FastAPI shares the database dependency within the request; do not open a different
transaction after an authorization dependency and assume its lock protects it.
For write routes, use `with application_database() as db` inside the authenticated
handler/service, authorize and mutate there, and exit the context before returning
success. `/api/me` follows this pattern for lazy provisioning. Agent B must account
for FastAPI yield-dependency teardown timing. Repository
helpers are also usable in an explicit service transaction.

`create_owned_meta_connection` is an insert-only transactional primitive. Agent C
passes an already encrypted token, then creates session/jobs in its outer transaction.
A duplicate `external_user_id` raises a uniqueness conflict, without overwriting or
claiming an existing connection. `require_owned_meta_connection` checks the verified
user and locks the matching row; NULL or another owner fails. Reconnection must
check ownership before updating credentials. Agent C must also guard all provider
reads, connect initiation, disconnect, jobs, OAuth state and callback binding.
Current Meta cookies are legacy provider-session state, never application identity.

## Routes and errors

- `GET /api/me`: authenticated; lazily creates an empty profile idempotently and
  returns `{user_id,email,profile:{display_name}}`. No raw claims/provider IDs.
- `GET /api/me/companies`: authenticated, returns `{companies:[{id,name,created_at,
  archived_at,role}]}`; accepts `include_archived` (default false).
- Both use `Cache-Control: private, no-store`. Auth errors are also non-cacheable.
- 401: absent header is `Authentication required.`; malformed/invalid/expired
  credentials are `Invalid or expired credentials.`; both challenge with Bearer.
- 403: authenticated membership/role/active-company failure, including a missing
  company, with the same generic `Company access denied.` to avoid existence leaks.
- 503: unavailable/misconfigured auth or unavailable database, without internals.

Health remains public. Provider callbacks require their OAuth protections and
remain reachable as required. Agent B protects company/content/ideas/generation;
Agent C protects Meta initiation and provider resources. Do not install blanket
middleware that accidentally blocks callbacks or treats cookies as app identity.

## Browser and database security

Agent D configures `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`; neither
is needed by this backend foundation. Never put service-role/secret/signing keys
in browser code. Let the Supabase client manage refresh/session persistence, send
tokens over HTTPS to the application API only, clear user-scoped caches on sign-out
or identity change, and do not log tokens or put them in URLs. Persistent browser
tokens require normal XSS defenses. No tokens belong in application tables.

Selected-company localStorage state is navigation convenience **only**. Validate
it against `/api/me/companies` after login; every protected backend request must
independently enforce membership. Hiding UI is not access control.

The two new tables have RLS enabled with **no policies**, denying all access for
ordinary roles even if Supabase grants table privileges. Backend DATABASE_URL must
use the table owner or a dedicated BYPASSRLS role with appropriate SQL privileges;
there is no per-request Supabase database session. Existing application-table RLS
and grants are not changed here. Production integration must verify those tables
are not exposed through anonymous/authenticated Supabase Data API grants (or disable
the Data API for application schemas). Browser application-table access is unsupported.
FastAPI checks remain mandatory regardless of RLS. No production configuration was
inspected or modified, so this is not a claim of production security readiness.

## Agent handoff and testing

Keep `auth.py`, `auth_dependencies.py`, `auth_repository.py`, `auth_routes.py`,
migration 011 and their tests stable across B–D. Coordinate changes to `main.py`,
requirements, `.env.example`, DATABASE.md and this contract to avoid merge conflicts.
Never edit 001–011 after branching; add a later migration for schema changes.
B owns company/resource retrofit, C Meta OAuth/ownership retrofit, D browser auth.
V7 can create an owned workspace before connecting Meta. V8 billing belongs to
companies, not individual users. No billing, onboarding gamification or team UI is
introduced here.

`tests/auth_fixtures.py` creates local ES256 tokens and a matching JWKS; tests replace
only JWKS fetch transport through a verifier dependency override. Production
signature/issuer/audience/time/role/UUID verification runs unchanged. RSA is tested
as well. No live Supabase calls or permissive production test mode are required.
PostgreSQL tests use isolated schemas via `TEST_DATABASE_URL` and drop them after
each test. Fresh 001–011 and populated 001–010 then 011 are separate cases. Failure
injection verifies rollback; concurrent SQL verifies membership/company locks.

Run from backend with installed requirements:

```sh
TEST_DATABASE_URL=postgresql://localhost/disposable python -m unittest discover -s tests -v
# Optional existing actual media integration (requires local models):
TEST_DATABASE_URL=postgresql://localhost/disposable RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 python -m unittest discover -s tests -v
python -m compileall -q app tests
```

Live Supabase signing configuration, password/Google/email flows, provider OAuth,
production RLS/grants, hosted deployments and frontend auth UI require later agents
and integration verification. Local signed tokens prove the verifier contract, not
live provider configuration.

## Agent A validation record

Final full backend run: 321 tests passed, zero skips, with disposable PostgreSQL 17
and RUN_MEDIA_INTEGRATION=1/HF_HUB_OFFLINE=1 (53.617 seconds). Includes 27 new auth
cases, of which 13 exercise real PostgreSQL: fresh and populated migration paths,
migration rollback, unchanged legacy relationships/history, role/access isolation,
transaction rollback, lock retention and profile-commit failure handling. Existing
V5 snapshot tests now explicitly expect NULL owner_user_id while still comparing
every original value. No tests were disabled.

Existing frontend suite: 224 passed, zero skips (179.352 seconds), including real
API/database browser integrations and desktop/mobile/320px checks. Browser plugin
was unavailable; the existing Playwright suite was used. TypeScript check and Vite
production build passed. Python compileall and git diff --check passed. No Python
lint/type-checker or frontend lint script is configured. Test logs contain existing
deprecation/native media-library warnings, without failures. Verification used
PyJWT 2.15.0 and the existing cryptography 46.0.7, within declared requirements.

Security review covered unsigned/none/symmetric token rejection, issuer/audience
and UUID binding, request/localStorage identity spoofing, membership and owner
checks, archived/missing company behavior, cross-company isolation, unclaimed
legacy data, atomic ownership, token logging and secret/public key separation.
No unresolved issue was found in the new foundation. Commit-before-response for
lazy profile creation was tightened during review and failure-tested. This does
not certify the deliberately unconverted V5 routes or live production settings.
