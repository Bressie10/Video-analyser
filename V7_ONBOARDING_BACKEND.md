# V7 onboarding backend

Foundation: audited V6 commit `0758c39e09acdc7b33bfcf8305c1067c1ef682bd`.
Apply `backend/migrations/013_onboarding_state.sql` after 001–012. The migration
adds `user_onboarding_state`: a Supabase UUID logical identity reference through
`user_profiles`, nullable `onboarding_company_id` referencing `companies` with
`ON DELETE SET NULL`, `welcome_seen_at`, `onboarding_skipped_at`, and created/updated
timestamps. It stores UX choices only. There is no auth.users FK, progress column,
step flag, or completion mutation. A missing row is valid for all existing users.

## API

All endpoints require a signed Supabase Bearer token and return private, no-store
responses. The JWT subject is the only application identity.

- `GET /api/me/onboarding` returns `{company_id, welcome_seen, skipped, progress,
  complete, next_step, steps}`. `company_id` is a UUID or null. `steps` has the
  lowercase keys `workspace`, `meta`, `account`, `analysis`, `idea`. `progress` is
  20 times the number of true flags; `complete` is true only when all five are
  true; `next_step` is the first false key in that order, or null.
- `POST /api/me/onboarding/welcome` sets `welcome_seen_at` once and returns the
  current state. Repeats preserve the original timestamp.
- `POST /api/me/onboarding/skip` sets `onboarding_skipped_at` once and returns the
  current state. Repeats preserve the original timestamp. Skip never completes a
  functional step. The setup reminder can remain until derived completion.
- `PUT /api/me/onboarding/company` accepts `{ "company_id": "<uuid>" }`, checks
  active membership in the same transaction as the write, stores the anchor, and
  returns current state. Selecting the same company preserves `updated_at`.
  Unknown, archived, foreign, and unclaimed companies return the same 403.
  The endpoint changes neither membership nor the app's active company.

There is no `/complete`, `/step`, or progress mutation endpoint.

## Derivation and effective company

Each GET runs one bounded SQL statement over the authenticated user's active
memberships. The company anchor is the stored ID only while that company exists,
is not archived, and remains accessible to the user. Otherwise, the statement
chooses the active accessible company with the highest count of company-level
conditions (`account`, `analysis`, `idea`), then earliest `created_at`, then UUID.
This fallback is read-only. Explicit selection is the only way GET's fallback
becomes persistent. An archived, deleted, or membership-revoked stored company
therefore cannot grant access or pin progress to an inaccessible workspace.

- `workspace`: at least one active, non-archived company membership.
- `meta`: at least one personally owned Meta connection whose existing status is
  `connected`, token ciphertext exists, and expiry is in the future. A connection
  owned by another user or left unclaimed does not count.
- `account`: effective company's linked Facebook or Instagram organic account.
  A linked Meta Ads account alone does not count.
- `analysis`: effective company has a currently accessible organic library item
  with `analysis_state='completed'`, current repository `ANALYSIS_VERSION`, and a
  same-version video on the same connection. Accessibility follows V6's direct
  organic account link or assigned-ad creative relationship. Other states and
  stale versions do not count.
- `idea`: at least one persisted idea for the effective company, including ideas
  generated before V7. It remains historical even if Meta later disconnects.

The booleans are independent. For example, Meta disconnecting after 100% changes
only `meta` to false and progress to 80%; the earlier account, analysis, and idea
records remain visible as setup history while their company relationships exist.
Existing V6 users with real product state can reach 100% with no onboarding row.
A new user starts with null company and 0%; company creation alone satisfies
`workspace` and needs no Meta connection.

## Authorization, RLS, and frontend integration

The boundary remains Supabase JWT → `AuthenticatedUser` → company membership →
company resource. Browser-selected company IDs are navigation/UX input only.
`PUT` checks membership server-side and gives no foreign-company existence detail.
`GET` filters candidate companies by the authenticated user's memberships before
examining account, content, or idea state. Meta is filtered by owner UUID.

The new table has RLS enabled with no policies, matching V6 default-deny tables.
FastAPI must connect as table owner or a role with `BYPASSRLS`; production Data API
grants and role configuration remain deployment checks. Existing RLS is unchanged.

Frontend Agent B can call GET after sign-in and after relevant company, Meta,
account, analysis, or idea changes. Call `welcome` when the welcome screen is seen,
`skip` when the user elects to enter the app, and `company` only after an explicit
onboarding company choice. Use `skipped` for navigation/reminder UX and `complete`
for actual setup health. The API never selects the app's active company.

Local integration tests use signed test JWTs and disposable PostgreSQL. They do
not verify live Supabase, Meta, production RLS grants, or deployed configuration.
