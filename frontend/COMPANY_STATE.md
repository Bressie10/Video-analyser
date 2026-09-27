# V4 company state and data access

`src/company/CompanyProvider.tsx` installs one store at the application root.
The production selector and management UI consume this store through `useCompanyUI`. No new dependencies.

## State contract

`useCompany()` exposes `status` (`loading`, `ready`, `error`), `companies`,
`activeCompanyId`, `activeCompany`, `error`, `persistenceError`, `scopeVersion`,
and controlled `setActiveCompany`, `refreshCompanies`, `acceptCompany` and
`invalidateCompanyScope` actions. `ready` with a null ID is the no-company state.
Selection is allowed only after successful validation, and only for an accessible,
non-archived company. Nothing automatically selects the first company.

Startup first loads the complete accessible list, then reads and validates
`video-analyzer.active-company-id`. Only the normalized internal company UUID is
written to localStorage. No records, provider IDs, credentials, tokens, content,
performance or ideas are persisted. Missing/inaccessible/archived/invalid IDs are
removed. Network/5xx errors expose no scope, retain the UUID for an explicit retry,
and surface `error`. HTTP 401/403/404 clears selection and persistence. Storage
failures do not crash the app: state remains session-local; operation failures are
exposed in `persistenceError` (unavailable localStorage also reports this session-only
mode). Persistence is across refreshes, not a promise of cross-tab synchronization.

A refresh hides the active scope until revalidation succeeds. Refresh on known
access changes or after management mutations; there is no background access poll.
An archived active company is cleared, and restoring it does not select it.

## Consumption and race safety

Wrap future company-specific UI in `CompanyScopeBoundary`. It renders nothing
(or the supplied `fallback`) until the scope is validated. It remounts children
on scope changes/invalidation, resetting selected content, filters and other
local ephemeral state. Leave global UI outside it.

Use `useCompanyQuery(queryKey, load)` for company data. Memoize `load` with
`useCallback`; include filter identity in `queryKey`. The loader receives the
internal company UUID and an AbortSignal and should call a typed API module.
It refetches on company/scope/query changes. There is no cross-company cache:
render-time checks hide the preceding result immediately. Both cancellation and
scope/request generations guard commits, even if a transport ignores abort and
even for A → B → A. Errors from stale scopes cannot clear the current company.

HTTP 401/403/404 from this hook are treated conservatively as scope access failures:
they clear selection, hide scoped children and require explicit retry/reselection.
If a particular endpoint uses 404 for an optional/missing *item*, normalize that
case inside its loader instead of forwarding it as a company access failure.
Other query errors clear that query's data and surface its error without switching
company. No automatic retry loop.

For non-React consumers, `captureScope()` supplies the ID, signal and `isCurrent()`.
Check `isCurrent()` immediately before committing **any** response, including
mutation feedback; pass errors to `handleScopeError(scope, error)`.
`subscribeScope(reset)` provides a synchronous reset/invalidation subscription;
unsubscribe when disposing the consumer. `invalidateCompanyScope()` aborts current
requests and triggers refetch/reset without changing the selected ID.

After successful create, call `acceptCompany(created, true)` to add the returned
record and select/persist it immediately. Pass successful rename/archive/restore
records to `acceptCompany(record)`; these do not select another company. Never
pass optimistic or user-constructed records as authoritative backend responses.
On account/content mutations, invalidate the affected current scope (checking a
captured scope first); refresh companies when accessibility may have changed.
Management lists can use the API without an active company.

## Backend adapter

`src/company/companyApi.ts` implements the authoritative [company API](../backend/COMPANY_API.md).
It requests `/api/companies?include_archived=true` for management, normalizes
`company_id`, `account_id`, `ad_item_id` and friendly display names, and retains
company account links. Lists are unpaginated `{companies}`, `{accounts}`, and
`{ads}` envelopes. The assignable-ad request includes both the inspected company
and linked Ads-account UUID. Ownership mutations use the company-specific routes;
reassignment is one atomic POST, never an unlink/link pair.

Requests carry the same-origin session cookie, no-store policy, cancellation and
20-second timeout. Parsers project supported fields and validate UUIDs. Failures
retain HTTP status and render safe operation-specific copy, including 409 organic
ownership and blocked Ads unlink messages. Raw server error payloads are not shown.

`useCompanyUI` serializes through shell actions and applies successful backend
responses to the global store. The inspected management company is distinct from
active selection. Discovery results are keyed by inspection, scope, account links
and request revision; render-time checks and cancellation reject stale results.
Ownership changes invalidate scoped state. Restoring never selects a company.

## Wave 2 boundary and checks

Production does not mount the unscoped V2 library, background library polling,
processing or recommendation controls. The legacy browser regression fixture is
under `tests/legacy.html` and is excluded from the production build. Account links
are not treated as proof of content presence. Empty companies remain valid.

Wave 2 must adapt content reads to the V3 ownership helpers, add the minimal
company-scoped HTTP routes, and integrate processing/generation with the scope
boundary and switch guards before enabling those screens. No generation, history,
feedback, lifecycle, publication, profile-settings or V5 redesign is included.

Run `npm run test:company`, `npm run test:companies`, `npm run test:e2e`,
`npm run typecheck`, and `npm run build`. Run `npm run test:company-integration`
with `TEST_DATABASE_URL` pointing to disposable UTF-8 PostgreSQL for the real
browser/FastAPI/database flow. `npm run test:integration` preserves V2's real
media/database regression. No lint script is configured. External Meta status and
provider boundaries are fixtures; these tests do not establish live Meta access.
