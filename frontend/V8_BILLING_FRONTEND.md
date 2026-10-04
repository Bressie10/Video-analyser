# ContentMetric V8 billing frontend

## Architecture and API

`BillingProvider` mounts inside the authenticated company workspace. It uses the existing `apiFetch` client and company scope capture for `GET /api/companies/{company_id}/billing`. The query clears immediately on company scope changes, rejects stale responses, and is removed on auth identity changes or logout with the workspace. Billing read errors remain local to Billing so an unavailable billing endpoint does not remove existing Content or Ideas. Settings renders `BillingSection` for the inspected company; a different inspected company gets its own cancellable read. Billing reads and management actions require no browser Stripe SDK or secrets.

The parser accepts the foundation's `plan`, `effective_plan`, `subscription_status`, `cancel_at_period_end`, `grace_until`, `entitlements`, `usage`, `period`, and `can_manage_billing` fields. `effective_plan` determines the displayed plan and limits. The backend remains the authority for permission, billing state, and consuming actions. 401 uses the shared auth recovery; 403/404 retain the signed-in session; 5xx and malformed responses show safe retry copy. Raw provider or database errors are never displayed.

## Settings and usage

Settings adds a compact Billing section using V5 controls, alerts, spacing and tokens. Free shows €0, current usage, period reset, an owner-only Upgrade action, and a short Pro comparison: €19/month per workspace, 50 analyses, 150 idea generations, 5 organic publishing accounts. Pro shows €19/month, current usage and period end with an owner-only Manage subscription action. `UsageIndicator` always prints the numbers and an explicit at-limit message alongside its progress element. Members can read billing but get no management controls. Only `can_manage_billing` enables those controls.

The backend's `past_due` plus effective Pro and `grace_until` produce a payment warning with the backend date. Cancellation keeps Pro visible until the effective plan changes and names the scheduled end date. If stored subscription metadata exists but effective access is Free, Settings displays Free limits and a restrained subscription notice. While a non-ended subscription remains, the owner uses Manage subscription rather than starting another Checkout. A downgrade never hides old content, analyses, ideas, profiles or linked accounts.

## Hosted billing flows and returns

Upgrade sends authenticated `POST /api/companies/{id}/billing/checkout`; management sends `POST /api/companies/{id}/billing/portal`. The frontend validates the returned HTTPS Stripe host, stores a short-lived session return marker and navigates with `window.location.assign`. The backend builds return URLs from `APP_ORIGIN`; Checkout success and cancellation both return to `/#settings`, and Portal also returns there. The return marker changes only messaging, never plan state. On return, billing is read and retried at most three additional times after Checkout or once after Portal. The marker expires and is cleared; no continuing poll runs.

## Limit errors and action UX

The narrow 402 adapter recognizes `detail.code` for `free_workspace_limit_reached`, `organic_account_limit_reached`, `analysis_limit_reached`, and `idea_generation_limit_reached`. Unknown 402 responses use safe generic errors. Agent B must return these stable codes; the frontend does not enforce quotas. After a recognized 402, billing refreshes even if the displayed usage suggested room remained.

Company creation explains the one owned Free workspace limit and directs the user to Billing. An organic link 402 leaves existing accounts and unlink controls intact; Ads accounts are excluded from the organic count. Content and Generate display action-level allowance notices while retaining existing content, analysis, ideas and drafts. Free limits offer an owner an upgrade path; Pro limits state the backend period reset date without promising a higher tier. Analysis acceptance, persisted idea generation, account linking, and relevant 402 responses trigger one billing refresh. There is no continuous usage polling.

## Onboarding and verification boundary

Billing adds no V7 onboarding step or payment wall. Free entitlements allow one workspace, one organic publishing account, three analyses and five idea generations; the existing V7 five-step route remains available. The existing company/auth boundaries handle A to B company switches and User A to User B remounts.

`tests/billing.test.mjs` uses deterministic authenticated API mocks and browser checks for plans, usage, owner/member controls, hosted navigation, bounded returns, stable limit codes, stale company responses, and 1440/1024/768/390/320px keyboard layouts. Live Stripe Checkout, Portal, webhook timing, production tax settings, live Supabase/Meta, and Agent B's future limit enforcement require separate staging verification. The frontend assumes the foundation read and hosted URL contracts exactly as documented in `V8_BILLING_FOUNDATION.md`.
