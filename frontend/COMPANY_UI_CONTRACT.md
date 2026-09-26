# V4 company UI integration

`src/CompanyShell.tsx` owns the permanent top-of-shell company selector, a dedicated management screen, setup/empty states, and guarded switching. It reuses the existing visual language and 600px breakpoint. `CompanyManagement`, `CompanySelector`, and `CompanyEmptyState` can also be composed separately. No router or dependency was added.

## Controlled state

Supply `CompanyUIProps` from `src/companyUI.ts` to `CompanyShell` (or the `App` prop in `src/main.tsx`). The current bootstrap deliberately supplies no adapter; it shows an integration-pending company control alongside the existing content flow. No companies are fabricated or persisted. The test-only fixture demonstrates a complete in-memory adapter.

- `companies`, `activeCompanyId`, and `status` are authoritative. Only non-archived companies are switch targets. Missing selection, loading, failure, archived selection, and valid companies with `hasContent: false` have distinct views. `hasContent` is a product-level workspace readiness flag; the integration determines it from linked/analyzed content.
- `accounts` and `adsContent` contain safe display names and opaque keys. UI never renders IDs. Supply only accessible records and use human-readable fallback names if Meta provides none. `linkedCompanyIds` and `assignedCompanyIds` control checkboxes.
- `discoveryStatus` and `onRetryDiscovery` govern discovered account/content loading. `metaConnected` describes the single broader Meta connection; `onConnectMeta` opens that shared connection flow.
- Mutations return promises, reject on failure, and publish refreshed props when successful. The shell serializes actions and shows a generic safe error without displaying raw provider errors. There is no optimistic ownership update or API access.
- `onSwitch(id)` must finish the real active-company transition before resolving. Enforce permissions/archive checks in the adapter/backend. Reset scoped selections, ideas, jobs, caches and requests there; this branch does not implement company scoping in the legacy data layer.
- `onCreate(name)` returns the created company and publishes it in `companies`. The shell then awaits `onSwitch(created.id)`, opens its workspace, and shows setup for `hasContent: false`. If activation fails, retrying the same name reuses the returned company for the lifetime of the mounted shell. Backend idempotency remains an integration concern if the creation request itself fails ambiguously.
- `onRename`, `onArchive`, and `onRestore` publish updated companies. An archived active company is shown as unavailable; the shell does not silently select another workspace. Restore makes it eligible for switching again.
- `onAccountLink(companyId, accountId, linked)` handles all three account kinds. `onAdsAssignment(companyId, contentId, assigned)` handles individual ads. Ads from linked accounts and already-assigned ads are inspectable; assigned ads remain removable even if an account was unlinked. The adapter owns conflict rules and any cascading unlink semantics.

## Guard registration

Within the shell, call `useCompanySwitchGuard({ unsavedEdits, generationInProgress })`. Multiple registrations aggregate; cleanup unregisters the caller. Keep registered work mounted while active. The shell keeps content mounted but hidden when management is open, so existing registrations persist. The hook is inert outside its provider.

Normal selection calls `onSwitch` immediately. A guarded selection opens a native modal dialog with Escape/cancel, focus containment and focus restoration. Confirming invokes the same action; the UI does not cancel generation or discard state itself. The adapter must implement that policy as part of `onSwitch`. Clicking the already active company is a no-op. New-company creation submits the creation form deliberately and confirms first if generation is active.

## Verification

`npm run test:companies` runs the isolated UI fixture in Chromium. `npm run test:e2e` covers the existing mocked frontend flows; `npm run typecheck` and `npm run build` check the production frontend. No lint script is configured. These checks do not establish real company API/database persistence, Meta access, account conflict rules, or company-scoped generation. The backend-dependent integration suite needs a disposable PostgreSQL environment and is outside this UI-only change.
