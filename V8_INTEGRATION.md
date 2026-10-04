# ContentMetric V8 integration

## Provenance and conflict resolution

Base: `00b9f61192ab4ff5777f7b052bdcb692106cb183` (billing foundation).
Cherry-picks, in order: `5a468c3077dc444ac1954ea17b5c2151a5a23b63`
(entitlements) and `f7ead63ff5ea38525d9674ba0db84bef6e0b9be9`
(frontend). Both applied without textual conflicts. The integration ties the
Checkout return marker to the authenticated user as well as the company; a
second user with access to the same company cannot inherit the first user's
return message or its bounded refresh cycle.

## Billing authority and plans

Supabase JWT identifies the user; company membership authorizes the resource.
The backend reads the company's persisted billing row, reconciles verified
Stripe webhook state, derives the effective plan, and checks the append-only
usage ledger. Frontend state, Checkout redirects and request data never grant
access. Free is €0 with one newly created owned Free workspace, one organic
Instagram/Facebook account, three analyses and five idea generations per
persisted billing period. Pro is €19 monthly per workspace with five organic
accounts, 50 analyses and 150 idea generations. V8 has no trial, annual, seat,
Business or Agency purchase flow.

Migration 014 follows 001–013. It adds `company_billing`,
`company_usage_ledger` and `stripe_webhook_events` with restrictive RLS.
An existing V7 company obtains a Free billing row on its first authorized
billing operation; historical content and usage are untouched. The ledger
contains immutable +1 reservations and -1 refunds. Billing reads sum entries
in the stored period, without a mutable quota counter. Free period rollover
retains old ledger rows. No integration migration is required.

## Entitlement paths and 402 contract

The company creation transaction locks the verified owner's profile and counts
only companies they own whose effective plan is Free. Membership alone does not
consume the slot. Existing owners of multiple legacy Free companies retain all
of them but cannot create another Free company until their effective billing
state allows it. Company and owner membership insertion remain atomic.

Organic account linking counts only Facebook and Instagram links. An existing
link may be replayed; Ads links do not count. Downgrade leaves existing links
intact, permits unlink, and blocks a new organic link while at or above the
current plan's limit.

New company-scoped analysis jobs reserve before worker work. Reused completed
analysis and existing queued/running work do not reserve again. Durable job IDs
key reservations. Completed jobs retain usage; failed, unavailable,
unsupported, cancelled and reused terminal jobs refund idempotently. Queued,
blocked and running jobs stay reserved. The billing row lock serializes the
last available slot. A member with permission consumes the same company quota.

Idea generation uses the existing company-scoped request ID, request hash and
durable claim. It reserves before calling the model. A persisted idea stays
charged; model, validation, authorization and persistence failures refund.
Saved-request replay returns the same idea without another charge. A stale
unfinished claim is refunded before replacement. A process crash may leave
usage reserved until that request is retried after its lease.

Limits return HTTP 402 with `{"detail":{"code":"...","message":"Plan limit reached."}}`.
The stable codes are `free_workspace_limit_reached`,
`organic_account_limit_reached`, `analysis_limit_reached` and
`idea_generation_limit_reached`. Authentication and company/child
authorization precede quota disclosure: unauthenticated callers receive 401;
foreign or insufficient company access receives 403, or 404 for inaccessible
children. The frontend reads `detail.code` from the real FastAPI shape.

## Expensive-route matrix

| Route or producer | V8 disposition |
| --- | --- |
| `POST /api/companies/{company_id}/content/analyze` | Authorized company job; analysis reservation before queue commit. |
| `POST /api/meta/library/analyze` | Verified provider owner and member of one linked company; metered jobs. |
| Meta sync, discovery and scheduler | Automatic jobs meter a unique linked/assigned company; ambiguous items defer. |
| `POST /api/meta/companies/{company_id}/recommendations` | Authorized company claim; idea reservation before model work. |
| `POST /api/meta/recommendations` | Authenticated legacy route returns 410 before model work. |
| `POST /api/videos/{id}/recommendations` | Video ownership checked; returns 410 before model work. |
| `POST /api/videos` | Authenticated legacy upload returns 410 before media work. |
| Company profile refresh | Separately authorized derived profile workflow with job coalescing and input-hash reuse; outside the two defined usage kinds. |
| Metrics refresh and GET routes | No content-analysis or idea model charge. |

## Checkout, Portal, webhooks and subscription state

Only an owner can POST Checkout or Portal. The backend supplies the existing
company Stripe customer, configured monthly Pro Price and `APP_ORIGIN`.
Neither Price nor customer nor subscription IDs are accepted from the browser.
An already effective Pro subscription returns 409 with Portal guidance.
Concurrent or rapid duplicate Checkout calls use the same deterministic
Stripe idempotency key under the billing-row lock. This reuses a session within
Stripe's idempotency retention window. After that window, the current design
can issue another completable Checkout Session while an earlier session is
still completable and local billing is Free. This is a residual duplicate
subscription risk requiring a staging Stripe check and operational monitoring;
the integration does not claim that Stripe idempotency prevents it indefinitely.

The frontend validates the returned Stripe HTTPS host and navigates. Returning
from Checkout or Portal triggers a fresh billing read and bounded retries;
the return marker changes messaging only. It cannot activate Pro. Members
have no management control, and direct backend POSTs remain owner-gated.

The public webhook verifies the signature over raw bytes and a bounded
timestamp. Its unique event claim and billing mutation share one transaction,
so duplicate delivery does not reapply and a failed transaction can retry.
Checkout completion, subscription created/updated/deleted, invoice paid and
invoice payment failed are handled. The backend retrieves current subscription
state for non-deletion events and verifies customer, company metadata, Price
and quantity. Only that verified state can activate Pro.

Active and trialing states grant Pro through the mirrored period end.
Past-due grants Pro only through the first stored three-day grace deadline;
repeated failures do not extend it. Invoice success clears grace. Incomplete,
incomplete-expired and unpaid use Free. A canceled subscription retains access
only through its legitimate mirrored paid period; deletion ends it. A downgrade
changes future consuming permissions without removing linked accounts, content,
analyses, ideas, profiles or history.

## Frontend and V7 interaction

Settings consumes the exact billing read fields: `plan`, `effective_plan`,
`subscription_status`, `cancel_at_period_end`, `grace_until`,
`entitlements`, `usage`, `period` and `can_manage_billing`. It shows
numeric usage, period dates, grace and cancellation text, and owner controls
only when the backend grants them. Free limits offer Pro; Pro limits show the
reset date without offering a nonexistent higher tier. Company scope changes
clear prior billing immediately and reject stale responses. Auth identity
changes remount the workspace, and return markers are user-bound.

V7 onboarding remains a separate derived product-state flow. Billing is not
an onboarding step. Free permits the first workspace, organic account,
analysis and idea needed to reach 100%. Existing workspaces remain visible
after a downgrade or for a legacy owner with multiple Free workspaces.

## Environment and release boundary

Backend variables: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_PRO_MONTHLY_PRICE_ID`, `APP_ORIGIN`, and existing V6/V7
Supabase, database, Meta and model variables. Optional
`STRIPE_AUTOMATIC_TAX=true` requests Stripe automatic tax only when its
account/product configuration supports it. No Stripe secret or service role
belongs in Vite variables. Keep `APP_ORIGIN` set to the actual current
production frontend origin; this integration does not change domains.

Before production: apply migration 014 with the required backend database
role; configure one recurring EUR 19 monthly Price, hosted Checkout, Customer
Portal, Stripe tax settings, HTTPS webhook and all six event subscriptions.
In Stripe test mode, smoke-test Checkout, completed payment, webhook timing,
Portal, scheduled cancellation, failed payment, grace expiry, and duplicate
Checkout attempts beyond the idempotency window. Then repeat the critical
payment and webhook path with live-mode configuration and confirm the current
frontend origin. Local provider fixtures do not establish live Stripe,
Supabase, Meta, model, worker or production deployment behavior.

## Local validation

The final sequential backend run passed 392 tests with zero failures and zero
skips using disposable PostgreSQL, provider fixtures and local media. It covers
fresh and populated V7-to-014 migration paths, rollback, RLS, webhook replay,
last-slot concurrency, V6 authorization and V7 onboarding. The final frontend
run passed 319 tests with zero failures and zero skips, including browser
integration with real FastAPI/PostgreSQL, a real workspace 402, billing usage
reads, foreign-user denial, company switching, keyboard and width checks at
1440, 1024, 768, 390 and 320 pixels. Python compilation, TypeScript typecheck,
production build and `git diff --check` passed. These local tests use mocked
Stripe, Meta and model boundaries; no live payment or production deployment was
tested.
