# Integrated V4 company UI

`CompanyShell` retains the existing selector, management layout, empty state and
native confirmation dialog. `main.tsx` mounts one CompanyProvider and supplies a
required real model from `useCompanyUI`; there is no production mock/bootstrap mode.
The shared Meta connection is available even without a selected company.

## Controlled behavior

- The store exclusively owns active selection and UUID persistence. The management
  inspection selection never implicitly changes the workspace.
- `hasLinkedAccounts` describes setup only; it makes no claim about content.
  Newly created companies are selected immediately and show setup/Skip for now.
- Archive clears active selection; restore only makes the company selectable.
- Available accounts and linked accounts use internal IDs and friendly labels.
  `discoveryCompanyId` fences presentation during inspection changes. Ads results
  come only from each inspected company's linked Ads-account selectors.
- Link/unlink, assign/unassign and atomic reassignment use real adapter callbacks.
  Reassignment targets are active companies linked to the same Ads account.
  409 conflicts remain visible and never trigger automatic ownership changes.
- The shell disables concurrent mutations and switching while saving. All errors
  use safe, actionable copy; retries reload authoritative data.

## Switch guards

`useCompanySwitchGuard({unsavedEdits, generationInProgress})` remains reusable.
Normal switching is immediate; pending work opens a keyboard-accessible dialog.
Cancel preserves state and persistence. Confirm changes the global company and
invalidates scoped state. Submitting a create form consumes that form's edits,
but still confirms other registered pending work. No generation UI is implemented.

## Verification

`test:companies` exercises the isolated UI fixture; `test:company` covers the real
store/adapter and React stale-request boundary; `test:company-integration` tests
production browser → FastAPI → disposable PostgreSQL, startup errors, ownership,
privacy and late responses. Existing V2 regressions run through a test-only HTML
entrypoint. See [state integration](COMPANY_STATE.md) and [backend contract](../backend/COMPANY_API.md).
