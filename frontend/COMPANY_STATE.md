# V4 company state and data access

`src/company/CompanyProvider.tsx` installs one store at the application root.
There is no selector or management UI in this branch. No new dependencies.

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
exposed in `persistenceError` (unavailable localStorage itself uses session-only
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

## Narrow adapter / provisional wire contract

`CompanyApi` is the stable frontend interface. All management paths, methods,
bodies, pagination and response parsing live in `src/company/companyApi.ts`.
The backend management branch is separate: the paths below are explicit
integration assumptions, **not verified live backend endpoints**.

| Operation | Provisional request |
| --- | --- |
| List accessible companies (including archived) | `GET /api/companies` |
| Create | `POST /api/companies` with `{name}` |
| Rename | `PATCH /api/companies/:id` with `{name}` |
| Archive / restore | `POST /api/companies/:id/archive` or `/restore` |
| Available Meta accounts | `GET /api/companies/available-meta-accounts` |
| Link / unlink internal account UUID | `PUT` / `DELETE /api/companies/:id/accounts/:accountId` |
| Assignable Ads content | `GET /api/companies/ads-content?after=...` |
| Assign | `PUT /api/companies/ads-content/:id/assignment` with `{company_id}` |
| Unassign | `DELETE` same path with `{company_id}` |
| Reassign atomically | `PATCH` same path with `{from_company_id,to_company_id}` |

List pages use `{items, next_cursor}`. Companies and accounts are fully paginated
before returning; Ads content exposes `Page<AdsContent>` for incremental loading.
Company responses are `{id,name,archived}`; accounts `{id,name,platform}`; Ads content
`{id,label,company_id}` (nullable assignment). IDs are internal UUIDs. Company
records are projected to these fields and frozen. Malformed wire data raises a
502 `ServiceError`; HTTP statuses are preserved. Requests use same-origin cookies,
`no-store`, caller cancellation and a 20-second timeout. No token storage.
Reassignment requires one atomic backend operation, never unlink-then-link.

## Integration work remaining

Reconcile the provisional adapter with the company-management branch, especially
archive representation, pagination, account IDs and assignment conflict behavior.
A missing management endpoint leaves the provider in error without a selected
company. Connect future selector/management UI to the actions above and render
appropriate loading, no-company, error and persistence-error states.

The existing V3 `App`/`VideoLibrary` and their unscoped endpoints are unchanged;
they are not converted into company-aware consumers by merely adding a provider.
Before showing those views as company-scoped V4 UI, migrate their API loaders to
company-scoped endpoints and put their content/selection/idea state inside the
boundary or use the scope subscription. This branch deliberately does not add
idea-generation/history features or alter the legacy visual flow.

Run `npm run typecheck`, `npm run test:company`, `npm run test:e2e`, `npm run build`.
The company tests cover store/adapter contracts and real Chromium React lifecycle
behavior with fixtures (including StrictMode); they do not prove live company
backend authorization, PostgreSQL ownership or Meta provider access. No lint
script is configured. The backend integration suite is outside this frontend-only
contract verification and requires its own database/media setup.
