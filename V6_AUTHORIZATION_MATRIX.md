# V6 company authorization (Agent B)

Foundation: `46768e51cf366e324f35fb5545f78195db0add34`.
Every route below requires a verified Supabase Bearer token. Missing, malformed,
expired or invalid tokens return **401**, including requests with valid Meta cookies.
The verified JWT subject is the only user identity; selected-company state is not
trusted. Responses are private/no-store; foundation authentication errors are no-store.

| Resource/action | Unauthenticated | Member | Owner |
| --- | --- | --- | --- |
| `GET /api/companies`, `/api/me/companies` | 401 | Own memberships only | Own memberships only |
| `POST /api/companies` | 401 | Any authenticated user creates a new owned company | Same |
| `GET /api/companies/{company_id}` | 401 | Yes, including archived summary | Yes |
| `PATCH /api/companies/{company_id}` (rename) | 401 | 403 | Active company only |
| `POST .../archive`, `.../restore` | 401 | 403 | Yes; repeated action is idempotent |
| `PUT .../accounts/{account_id}` | 401 | 403 | Active company + personally owned provider connection |
| `DELETE .../accounts/{account_id}` | 401 | 403 | Active company; existing ad-release restrictions |
| `GET .../accounts/{account_id}/ads` (assignment picker) | 401 | 403 | Active company and linked Ads account |
| `PUT/DELETE .../ads/{ad_item_id}` | 401 | 403 | Active company, existing account/assignment scope |
| `POST .../ads/{ad_item_id}/reassign` | 401 | 403 | Owner of **both** active companies; existing conflicts retained |
| `GET .../content` | 401 | Active company | Active company |
| `GET .../profiles`, `.../profiles/{scope}` | 401 | Active company | Active company |
| `POST .../profiles/{scope}/refresh` | 401 | Active company | Active company |
| `POST /api/meta/companies/{company_id}/recommendations` | 401 | Active company and accessible library items | Same |
| `GET .../ideas`, `.../ideas/{idea_id}`, `.../evidence` | 401 | Active company and company-owned idea | Same |
| `PATCH .../ideas/{idea_id}` (edit/lifecycle), `PUT .../feedback` | 401 | Active company and company-owned idea | Same |
| `GET .../ideas/{idea_id}/publications` | 401 | Active company and company-owned idea | Same |
| `PUT .../ideas/{idea_id}/publications/{library_item_id}` | 401 | Company-owned idea and currently accessible item | Same |
| `DELETE .../ideas/{idea_id}/publications/{library_item_id}` | 401 | Company-owned idea; historical association may be removed | Same |
| `GET .../publication-options` | 401 | Active company; directly owned organic posts only | Same |
| `GET /api/meta/accounts` | 401 | Only personally owned provider connections | Same |

Profile refresh remains an ordinary product operation: members already generate
ideas using these profiles, and refresh does not change company configuration.
The ad picker is administrative because it exposes unassigned provider inventory.
The general account picker has no company parameter and uses provider ownership;
linking still separately requires company ownership. Organic accounts attached to
unclaimed or inaccessible companies are omitted to avoid leaking company metadata.

## Errors, archive and legacy policy

**403** means missing membership/owner role, including unknown and unclaimed
companies. Active-only operations also return 403 for archived companies. Summary
reads and explicit archived listing preserve the existing management behavior.
Restore/archive require owner role, including on already archived companies.

After successful company authorization, inaccessible/missing child resources use
**404**, preserving the existing resource-hiding convention. An already assigned
ad or organic account still returns **409** when the existing ownership rule
requires explicit release/reassignment; conflict responses contain no foreign
company identity. Unassign/unlink retain their existing safe idempotent no-op
behavior where no relationship exists in the authorized company. An unowned or
foreign provider account submitted for linking returns 404.

No company or provider connection is automatically claimed. NULL-owner legacy
connections do not appear in the picker and cannot be newly linked. Existing
company memberships, if explicitly assigned administratively, authorize existing
company data independently of provider ownership/session/expiry. No admin claim
workflow is added.

## Preserved API and resource contracts

No routes or request/response shapes change. `/api/companies` retains the V4
`{companies:[{company_id,name,archived,accounts}]}` shape, now membership-derived.
`/api/me/companies` retains the foundation's `{id,name,created_at,archived_at,role}`
entries; Agent D can use its role for UI affordances. Neither listing is an auth grant.
The new company response remains `{company_id,name,archived,accounts:[]}`.

Creation calls `create_company_for_user` inside an explicit transaction: company,
profile and owner membership commit atomically before the successful response.
Companies start with `connection_id=NULL`. First successful account linking binds
that company to the account's connection, after checking company owner and the
foundation `require_owned_meta_connection`. The binding and existing link/profile
invalidation commit together; a conflict rolls everything back. An existing company
connection is never silently switched or cleared, even after its last unlink.

Content SQL, organic ownership, ad assignment, reusable/shared creative analysis,
metrics attribution, frozen idea evidence, one idea per request, idempotency,
history/edit/feedback/lifecycle and publication semantics remain unchanged.
**`video_ids` still contains `library_item_id` UUIDs, not stored video UUIDs.**
Publication cursors and idea cursors remain checked inside their company scope.
Provider disconnect/session expiration no longer blocks stored company data.

## Transactions and races

Explicit handlers commit before responding. Authorization and protected mutation
share the same database transaction. The new helper resolves persisted connection
IDs, locks connections in UUID order, locks companies in UUID order (write locks
up front for writes), then invokes foundation membership/role helpers. Membership
and company locks remain held through persistence, including both sides of an ad
reassignment. Existing connection and profile advisory locks/invalidation remain.
A company connection changed during initial lock discovery causes a safe 409 retry.

Generation repeats membership and source checks before capture and after the slow
model call; revocation/archive/source reassignment prevents persistence. Cleanup of
an already acquired generation claim remains an internal service cleanup, not a
new user operation. Listing uses a single membership/account snapshot to avoid
per-company lock-order inversions; the provider account picker locks memberships
while reading company labels. No worker authorization or scheduling is changed.

## Full route-surface audit and Agents C/D integration

Company management/content, profile, and all persistent-idea routes above are
converted. Their Meta-cookie application authorization is removed. The shared
foundation files and migrations 001–011 are unchanged; no migration is added.

The remaining route surface was inspected:

- `/api/me` and `/api/me/companies`: foundation JWT routes, unchanged.
- `/api/meta/connect`, callback/test/disconnect; discovery pages, Instagram media,
  Ads accounts/ads; library list/detail/batches/jobs/sync and connection-wide
  `/api/meta/recommendations`; Facebook/Instagram/Ads metrics: **Agent C's provider
  boundary**. No company parameter or company-owned idea/profile API exists there.
  These can contain imported items also linked to companies; C must enforce owned
  connections throughout. This branch alone is not the complete public V6 cutover.
- `/api/videos/{video_id}/analysis` and `/recommendations`: legacy uploaded-video
  APIs. `read_analysis` rejects imported Meta videos without the matching connection;
  these HTTP routes do not supply one. They cannot bypass company access through a
  stored imported video UUID. Upload/photo and TikTok routes have no company mapping.
- `/health`, `/health/db` remain health endpoints. OAuth callbacks are unchanged.

**Agent C:** this branch consumes the stable `meta_connections.owner_user_id` and
foundation owned-connection helper; no uncommitted C interfaces are needed. B owns
`GET /api/meta/accounts` in `company_routes.py` and company-account binding. Keep
provider ownership checks/credential updates and the connection-first locking
convention compatible. This branch does not edit main.py or provider route modules. The one overlap to
resolve in `test_meta_library.py` is the OAuth callback crossover assertion: a Meta
cookie alone now returns 401 for company profiles and ideas.

**Agent D:** send Bearer headers to all company/profile/idea and account-picker
calls, even `/api/meta/companies/...`. Preserve existing API bodies. Use 401 for
sign-in, 403 for denied/archived company access, 404 for unavailable child resources,
and 409 for assignment conflicts/retry. A Meta connection is optional when creating
or using a company. Hide admin actions from members using `/api/me/companies.role`.

## Validation scope

Tests use local ES256-signed JWTs with only JWKS transport replaced, real PostgreSQL
migrations and real membership/resource adapters. Legacy behavior regressions are
updated to assert membership revocation rather than Meta-session revocation. The
old synthetic persistent-idea contract fixture remains explicitly test-only;
V6 security tests exercise the production adapter and real 001–011 schema.

Live Supabase project configuration, real OAuth/provider permissions, real model
responses, frontend login flows and combined C/D integration are not established
by these deterministic tests. No frontend files or API body shapes changed.

## Change manifest

Backend: `company_authorization.py` (new), `company_routes.py`,
`company_ownership_repository.py`, `company_profile_routes.py`,
`company_profile_company.py`, `idea_routes.py`, `idea_company_access.py`,
`idea_service.py`, all under `backend/app/`.

Tests: `company_auth_fixtures.py` and `test_v6_company_authorization.py` (new);
`test_company_api.py`, `test_company_content_api.py`,
`test_company_profile_integration.py`, `test_company_profiles.py`,
`test_idea_feedback_publications.py`, `test_idea_integration.py`,
`test_meta_library.py`, `test_persistent_ideas.py`, `test_v4_idea_api.py`,
all under `backend/tests/`. This document completes the 20-file manifest.

## Final validation record

Clean complete run: **335 tests passed, zero failures/errors, zero skips** in
68.587 seconds, including all migrations on disposable PostgreSQL 17, transaction
rollback/concurrency checks, 14 new V6 security tests, and actual local media tests.
Command from `backend/` (the local environment supplies installed requirements):

```sh
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55463/postgres \
RUN_MEDIA_INTEGRATION=1 HF_HUB_OFFLINE=1 \
PYTHONPATH=tests:/private/tmp/contentmetric-v6-jwt \
/Users/ultanbreslin/Downloads/Video_Analyzer/backend/.venv/bin/python \
-m unittest discover -s tests -v
```

The temporary JWT path contains the foundation's already installed PyJWT package;
no dependency declaration or main-checkout environment was changed. Final log:
`/private/tmp/v6-company-final.log`. Python compilation (`compileall -q app tests`)
and `git diff --check` passed. No configured Python lint/type checker was found.
No frontend tests/typecheck/build were run: no frontend files or API body shapes
changed; authenticated frontend integration belongs to D and the combined audit.

Security review found no unresolved company-route bypass: JWT identity, owner/member
separation, foreign child IDs, unclaimed legacy companies, archive restrictions,
provider-cookie independence, transactional ownership checks, generation rechecks,
and two-company reassignment locking are covered. The review caught and fixed the
outer transaction boundary for creation; an injected post-creation read failure
now rolls back the company and membership. C's provider cutover and live deployment
validation remain separate requirements, as described above.
