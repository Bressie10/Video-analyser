# ContentMetric V8 billing foundation

## Scope and schema

Billing belongs to a company. `014_billing_foundation.sql` adds `company_billing`,
`company_usage_ledger`, and `stripe_webhook_events`. Apply it once after 001–013.
Existing companies are not backfilled: the first authorized billing read or operation
creates a Free row and a persisted monthly period. The three tables have RLS enabled
without browser policies. FastAPI must connect with the application table owner or a
dedicated role with the required privileges; browser Data API access is unsupported.
The migration does not change company memberships or provider authorization.

`company_billing.company_id` is the primary key. Stripe customer and subscription IDs
are individually unique. A company has at most one stored Stripe customer and one
stored subscription at a time. `plan_code` is `free` or `pro`; effective access is
derived from subscription status and time. Period start/end are explicit. No user
profile contains Stripe state. The only committed product plans are Free (€0) and
Pro (€19/month per company); create the recurring EUR 19 monthly Price in Stripe.
Limits are defined in `billing_repository.LIMITS`: Free 1 organic account, 3
analyses, 5 idea generations; Pro 5, 50, 150. This foundation records and reports
usage; existing analysis/generation routes do not enforce these limits yet.

Free periods roll from their persisted end under a row lock, advancing monthly
until the current period contains the request time. Historical ledger events remain.
Legacy companies start their first V8 Free period on first billing initialization;
past usage is not charged. Pro periods use the configured Price's subscription item
`current_period_start` and `current_period_end` from Stripe. Periods use inclusive
start and exclusive end. If a renewal webhook is delayed beyond the mirrored end,
reads temporarily start a Free period; a later verified active update restores Pro.
A paid entitlement ending starts a new Free period from
the downgrade point. Neither downgrade nor cancellation deletes product data.

## Checkout, Portal, and customer mapping

`POST /api/companies/{company_id}/billing/checkout` requires a verified Supabase
JWT and owner membership. The server creates or reuses the company's Stripe customer
under the billing row lock and creates a hosted Checkout Session with
`mode=subscription`, one unit of `STRIPE_PRO_MONTHLY_PRICE_ID`, company metadata,
and return URLs built from `APP_ORIGIN`. Request bodies, Origin/Referer headers,
query strings, and redirect success do not grant Pro or select a Price/customer.
Customer creation uses a deterministic Stripe idempotency key. Before a new
Checkout, the server checks the company's Stripe customer for open Sessions and
non-ended subscriptions. An open company Session is reused; a subscription
blocks another Checkout even before its webhook arrives. New Checkout attempts
use distinct idempotency keys after an old Session expires. An already effective
Pro company is directed to Portal instead. Provider list and timing behavior
must be checked in Stripe staging before release.

`POST /api/companies/{company_id}/billing/portal` requires an owner and an existing
company customer. It returns the server-created Stripe Customer Portal URL. Configure
the Portal for payment method management, cancellation, and subscription management.
Only server-created HTTPS destinations on Stripe hosts are returned. Frontend Agent C
can navigate to `url`; it needs no Stripe publishable key or card form.

## Webhook and subscription states

`POST /api/stripe/webhook` is public to Stripe and authenticates raw request bytes
using `Stripe-Signature`, `STRIPE_WEBHOOK_SECRET`, and a five-minute timestamp window.
No Supabase bearer token or Meta cookie applies. The transaction first claims the
unique event ID, then mutates company billing. A failure rolls back both, allowing
Stripe retry. Duplicate event IDs return `processed: false` without mutation.
Recognized events: `checkout.session.completed`, `customer.subscription.created`,
`updated`, `deleted`, `invoice.paid`, `invoice.payment_failed`. Checkout and invoice
events retrieve the current Stripe subscription; created/updated subscription events
also retrieve current state to avoid applying stale deliveries. Deletion uses the
signed event object. Customer mapping and any present company metadata must match, and the
single subscription item must use the configured Pro Price and quantity one.
Unknown customers or malformed paid events fail for retry/investigation.

| Stripe status | Effective entitlement |
| --- | --- |
| active | Pro through the mirrored paid period end |
| trialing | Pro through the mirrored period end if unexpectedly encountered; V8 creates no trial |
| past_due | Pro until first persisted `grace_until`, three days after first failure; then Free |
| canceled | Pro until mirrored paid period end when a period remains; deletion starts Free immediately |
| incomplete | Free |
| incomplete_expired, unpaid | Free, with a fresh Free period |

An active/paid update clears grace. Repeated failures preserve the first grace
deadline. Reads after grace or canceled period expiry initialize a Free period at
the expiry point. Pro content and connections remain stored on every downgrade.
The webhook must be registered for the listed event types and delivered over HTTPS.

## Ledger and Agent B integration

`company_usage_ledger` records company, kind (`analysis` or `idea_generation`),
integer delta (`+1` reservation or `-1` reversal), globally unique idempotency key,
source type/identifier, reason, and timestamp. UPDATE/DELETE triggers reject changes.
Current usage is `SUM(delta)` for the company/kind and active persisted period.
There are no authoritative mutable counters. A repeated key returns the same event
only when all immutable claims match; a cross-company or changed claim raises an
error. The billing row is locked before the append, serializing concurrent callers.

Entitlement Agent B should authorize the company in the same database transaction,
call `billing_repository.initialize(db, company_id)`, inspect
`effective_plan(row)` and `LIMITS`, and use `usage(db,row)` while holding the row lock.
Reserve with `record_usage(db, company_id, kind, +1, deterministic_key, source_type,
source_identifier, 'reserve')` before starting durable work. Use distinct reserve and
refund keys, such as `analysis:<job-id>:reserve` and `analysis:<job-id>:refund`.
Append a `-1` reversal for an eligible failure, never mutate the reservation.
Use durable operation IDs so retries and multiple workers share the same key.
Place decision, reservation, and durable work creation in one transaction. Agent B
owns enforcement in analysis, generation, and account-link workflows.

## Read API and authorization

`GET /api/companies/{company_id}/billing` allows active company members. It returns
`plan`, `effective_plan`, `subscription_status`, `cancel_at_period_end`, `grace_until`,
`entitlements`, `usage` (`analyses`, `idea_generations`), `period` (`starts_at`,
`ends_at`), and `can_manage_billing`. Owner-only Checkout and Portal return `{url}`.
Missing/foreign/archived company access is 403; no bearer token is 401. Responses
carry no Stripe customer, subscription, secret, or full provider object. Browser
plan flags and Checkout redirects are display/navigation only.

## Environment and production setup

Backend only: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`STRIPE_PRO_MONTHLY_PRICE_ID`, and `APP_ORIGIN` (the deployed frontend HTTPS origin).
Optional `STRIPE_AUTOMATIC_TAX=true` asks Stripe Checkout to calculate automatic tax
when the Stripe account and Product are configured for it; no tax rates are coded.
Keep secrets out of frontend environment and version control. Set the actual current
origin; no future domain is hard-coded. Configure a Stripe Product and one monthly
EUR 19 Price, hosted Checkout, Customer Portal, webhook endpoint and subscribed event
types, Stripe Tax/tax settings appropriate to the business, and production database
migration/role privileges. Do not invent tax rates in application code. Checkout's
automatic tax behavior remains a Stripe account/product configuration concern.
Verify test-mode and live-mode keys, Price, endpoint secret, Portal settings, tax mode, and
return origin separately before launch. Local provider mocks and PostgreSQL tests
do not prove live Stripe delivery or production tax configuration.
