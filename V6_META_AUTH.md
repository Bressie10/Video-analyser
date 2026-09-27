# V6 Meta authorization

This branch starts at `46768e51cf366e324f35fb5545f78195db0add34` and requires
migrations 001–011. It does not change the foundation identity model or migrations.
Apply it with Agent B's resource authorization and Agent D's authenticated browser
requests before releasing V6. Company routes in this isolated branch still have
V5 authorization; this branch alone is not a public-use V6 release.

## Application identity and provider state

Supabase's verified Bearer JWT identifies a ContentMetric user. The Meta cookie
only selects a provider connection. All Meta library, discovery, Facebook,
Instagram and Ads routes now require the application auth dependency and check
that the persistent connection selected by the cookie belongs to that user.
A valid cookie for another user or a NULL-owner legacy connection returns 403.
Missing/stale provider sessions return 401 on provider operations. `/api/meta/test`
requires a JWT, reports `{connected:false}` for missing/stale sessions, and returns
403 for foreign/unclaimed sessions without contacting Meta or revoking their
sessions. Configuration/storage errors remain 503, provider failures 502 and
provider permission failures 403. Provider tokens/ciphertext are never returned.

The underlying provider-only helpers remain internal mechanics for legacy callers
and workers; they are not application authorization. Agent B must independently
protect company routes with membership checks. Owning a Meta connection is not
company membership, and membership does not grant arbitrary access to the owner's
other provider connections.

## Connect and callback contract (Agent D)

1. Send `GET /api/meta/connect?response_mode=json` with the Supabase Bearer JWT
   and browser credentials. It returns `{authorization_url}` and sets the state
   cookie. Navigate the browser to that URL. Default `response_mode=redirect`
   preserves the 302 response for clients able to initiate authenticated navigation.
   A normal anchor/window.open cannot add the JWT; do not put the JWT in a URL.
2. Meta returns to the configured HTTPS `/api/meta/callback`. No application JWT
   is required on this callback. It returns the existing JSON success shape
   `{connected:true,job_id}` or a safe JSON error; no frontend/domain redirect was
   added. Agent D can retain the current popup-close/status-refresh interaction.
3. Include the application Bearer JWT and browser credentials on subsequent
   `/api/meta/test`, library, discovery, sync, jobs and disconnect requests.
   Clear frontend user-scoped state on logout/user change. A stale other-user cookie
   is rejected; it cannot cause automatic ownership reassignment.

Connect now requires valid encryption configuration as well as Meta configuration;
there is no V6 ownerless in-memory-session fallback. New sessions use Secure,
HttpOnly, SameSite=Lax cookies at `/api`; the narrower legacy cookie is expired on
success and disconnect. Cookies still reaching company paths confer no app identity.

## OAuth state security

The server generates 256-bit random opaque state. A bounded server-side map binds
it to the verified initiating UUID, Meta configuration and a 600-second expiration.
The state contains no user ID or token. A Secure/HttpOnly/SameSite=Lax cookie scoped
to `/api/meta/callback` must match it using a constant-time comparison. Missing,
malformed, mismatched, unknown, expired and already-used states return 400 before
code exchange. Atomic removal under the existing process lock permits one callback,
including concurrent callbacks. Provider cancellation/failure also consumes state.
The callback always expires its state cookie. Callback `user_id` parameters and
Authorization headers cannot select or replace the initiating owner.

State remains process-local, consistent with the existing Meta design: run one API
worker or provide reliable connect/callback affinity. Restarts and cross-worker
callbacks fail closed and require a new login. A shared durable state store is
future work for multi-worker operation; do not claim this design provides it.
At most 1024 pending states are retained; expired states are purged on initiation.

## Ownership, reconnection and concurrency (Agent B)

`connect_identity(..., owner_user_id=verified_uuid)` now requires a UUID, validates
the provider identity and encrypts the token with the existing Fernet key. Profile,
connection, session, blocked-job recovery and initial sync commit atomically.
The external Meta identity's existing unique constraint remains authoritative:

- New identity: create an owned connection.
- Same owner and same identity: refresh token/expiry/status on the existing UUID.
- Different owner: 409; do not update token, owner, sessions or jobs.
- NULL-owner legacy row: 409; preserve it unchanged, with no automatic claim.

The PostgreSQL `ON CONFLICT DO UPDATE ... WHERE owner_user_id=EXCLUDED.owner_user_id`
condition runs under the conflicting row lock. Concurrent different-owner attempts
produce one winner and one conflict; concurrent same-owner attempts share one
connection and active sync. This is not a read-then-unconditionally-write check.
No one-user-one-connection constraint was added. Rotating a previous session removes
it only if it belongs to the reconnected connection; a supplied foreign cookie is
never revoked by the callback. Other valid sessions for the same owner may remain.

Integration helpers in `meta_library_repository.py`:

- `list_meta_connections_for_user(db,user_id)`: safe id/status/expiry projection.
- `require_meta_connection_owner(db,user_id,connection_id)`: delegates to the
  foundation locked ownership check; raises `CompanyAccessDenied` on missing,
  foreign or NULL owner. Call inside the same transaction as the protected mutation.
- `list_meta_accounts_for_user(db,user_id,connection_id)`: ownership check plus
  internal account id/platform/label projection, without provider IDs or secrets.

Use only the verified JWT UUID with these helpers. Agent B must check company role
and connection ownership before explicitly linking accounts. No company links are
inferred from a cookie. Ownership transfers/admin legacy claims are unsupported;
any future transfer must coordinate locks, revoke sessions and reauthorize jobs.
No legacy data is deleted or claimed.

## Security review and validation scope

Reviewed OAuth CSRF, atomic replay prevention, cookie/context substitution, expiry,
callback identity substitution, cross-user access, legacy claims, encrypted token
storage, safe error/log output, reconnect races and session rotation. The callback
needs both the high-entropy server state and matching browser cookie; provider-cookie
theft alone cannot access Meta routes without the owner's valid application JWT.
Existing Graph token/URL log redaction and encryption-at-rest remain unchanged.
Compromise of both credentials or browser execution remains outside that guarantee.

Deterministic tests use locally signed ES256 JWTs with mocked JWKS transport, mocked
Meta responses and real isolated PostgreSQL schemas. Existing provider-payload unit
tests explicitly override the ownership dependency; the new V6 tests exercise the
real auth and ownership boundary instead. The library suite now applies 001–011
and provisions owned connections. No tests are disabled or removed.

Live Supabase/Meta consent, production HTTPS cookies, provider permissions,
production grants/configuration and the integrated B/D frontend are not verified by
these tests. The unchanged V5 frontend requires Agent D's Bearer-request changes.

## Changed files

- `V6_META_AUTH.md`
- `backend/app/facebook_routes.py`
- `backend/app/instagram_routes.py`
- `backend/app/meta.py`
- `backend/app/meta_ads_routes.py`
- `backend/app/meta_auth_dependencies.py`
- `backend/app/meta_discovery.py`
- `backend/app/meta_library_repository.py`
- `backend/app/meta_library_routes.py`
- `backend/app/meta_routes.py`
- `backend/tests/company_browser_server.py`
- `backend/tests/frontend_integration_server.py`
- `backend/tests/test_facebook_api.py`
- `backend/tests/test_facebook_database.py`
- `backend/tests/test_instagram_api.py`
- `backend/tests/test_instagram_database.py`
- `backend/tests/test_meta_ads_api.py`
- `backend/tests/test_meta_ads_database.py`
- `backend/tests/test_meta_api.py`
- `backend/tests/test_meta_discovery.py`
- `backend/tests/test_meta_library.py`
- `backend/tests/test_meta_v6_auth.py`
- `backend/tests/wave2_browser_server.py`
- `frontend/tests/company-integration.test.mjs`
- `frontend/tests/integration.test.mjs`
- `frontend/tests/wave2-integration.test.mjs`

The browser integration harnesses now supply locally signed JWTs through Playwright
headers and explicitly provision fixture ownership. They mock JWKS transport, not
JWT verification or provider-session ownership. This proves the backend contract;
it does not implement Agent D's browser login or token-refresh flow. Existing
company routes are still Agent B's integration responsibility.

## Final validation record

On 2026-09-27, after implementation and fixture changes were complete:

- One complete backend run: **332 passed, 0 failures, 0 skips**, 120.916 seconds.
  Includes 11 new signed-JWT/PostgreSQL V6 cases, existing Meta suites, migrations,
  rollback and concurrency checks, and actual cached-model media integration.
- One complete frontend run: **224 passed, 0 failures, 0 skips**, 199.086 seconds.
  Includes real browser/API/PostgreSQL integration with signed JWTs and explicit
  owners, Meta status/error handling, and existing desktop/mobile/320px checks.
  Browser plugin was unavailable; the repository's Playwright suite was used.
- Python `compileall` for app/tests, TypeScript `typecheck`, Vite production build
  and `git diff --check` passed. No Python lint/type checker is configured.
- Foundation auth modules and migration 011 are byte-for-byte unchanged.

Commands (from backend/frontend respectively, with requirements installed):

```sh
TEST_DATABASE_URL=postgresql://127.0.0.1:55449/postgres RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 python -m unittest discover -s tests -v
python -m compileall -q app tests
TEST_DATABASE_URL=postgresql://127.0.0.1:55449/postgres npm test
npm run typecheck
npm run build
git diff --check
```

Validation used disposable PostgreSQL 17 and existing local dependencies/models;
logs are `/tmp/v6-meta-backend-final.log` and `/tmp/v6-meta-frontend-final.log`.
Existing native-media/deprecation warnings remain, without test failures.
