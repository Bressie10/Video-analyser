# ContentMetric V8 entitlements and usage enforcement

Base: `00b9f61192ab4ff5777f7b052bdcb692106cb183`. No migration follows 014.
The company billing row and append-only usage ledger from 014 remain the only
authoritative usage store. Frontend state, provider cookies, request user IDs,
Stripe redirects, and email do not select an entitlement.

## Plans, ownership, and accounts

`backend/app/billing_repository.py` owns `LIMITS`, `initialize`, `effective_plan`,
and `usage`. Free allows one organic account, three analyses, and five persisted
idea generations per company period. Pro allows five, 50, and 150. The company
creation route serializes requests on the verified owner's `user_profiles` row,
then counts only owned companies with effective Free access. Membership does not
count. Existing owners of multiple Free companies keep all of them visible and
usable; the prospective creation check blocks another Free workspace. An owned
Pro company does not consume the Free workspace slot. Company and owner membership
are inserted in the same transaction after the entitlement check.

The account-link route checks the count under the company write lock and the
billing row lock in the link transaction. Only `facebook` and `instagram` links
count. `meta_ads` does not. Re-linking an existing account is idempotent and does
not need a new slot. Unlinking reduces the count. Downgrade never removes links:
an over-limit Free company can read its data and unlink, but cannot add another
organic link until its count is below the Free limit. A valid past-due grace
period uses the billing foundation's effective Pro plan; expiry uses Free.

## Ledger and concurrency

`entitlements.reserve_usage` is the shared transaction primitive. The caller
first authorizes the company and creates a durable operation in the same
transaction. Reservation initializes and locks `company_billing`, rolls a Free
period as needed, uses `effective_plan` and `LIMITS`, sums the ledger for the
active period, verifies any replayed idempotency key, rejects a full quota, and
appends one `+1` event. The billing row lock serializes final-slot contenders.
`refund_usage` verifies that the matching reservation exists and appends a
single `-1` event using its own deterministic key. It writes the reversal in the
reservation's original period, so a later refund cannot create negative current
period usage. The ledger is never updated or deleted. `GET .../billing` sums it
directly; there is no counter synchronization.

For analysis jobs the keys are `analysis:<meta_job_id>:reserve` and
`analysis:<meta_job_id>:refund`. For persisted idea generation attempts they are
`idea:<claim_id>:reserve` and `idea:<claim_id>:refund`. Claim IDs belong to the
existing request ID and hash contract. A replay of a saved idea returns it
without model work or a new reservation. An active request returns its existing
409 in-progress response; an expired claim is refunded before replacement.

## Analysis charging and terminal states

The V7 `POST /api/companies/{company_id}/content/analyze` route uses the
existing queue. The older `POST /api/meta/library/analyze` route can enqueue only
items linked to one company with a verified user membership; it authorizes and
rechecks that link under the company write lock. Connection-wide discovery and
sync use the same `queue_analysis` meter. Automatic work is deferred when no
unique active linked organic company or assigned Ads company can be identified,
or the quota is full. An Ads account link alone does not make every creative
billable to that company. A creative assigned to multiple companies is deferred;
no owner is guessed.
The discovery/sync operation itself and metric refreshes consume no analysis
unit. Queued/running jobs consume one unit. Reused completed analysis and an
existing queued/running job create no new reservation. The worker keeps a
completed job charged, refunds terminal `failed`, `unavailable`, `unsupported`,
`cancelled`, and `reused` jobs, and leaves queued/blocked/running work reserved.
Disconnect cancellation refunds in its database transaction. Worker retries
and repeated terminal callbacks cannot append a second refund.

## Idea charging

`POST /api/meta/companies/{company_id}/recommendations` keeps its existing
request ID, input hash, claim lease, company authorization, evidence capture,
and single persisted idea semantics. It reserves after the durable claim and
before the model call. A valid persisted idea remains charged. Model errors,
invalid output, failed evidence validation, failed final authorization, and
failed persistence refund and release the claim. An expired unfinished claim is
refunded when the same logical request is retried. A process crash can leave a
reservation pending until that request is retried after its lease; no browser
session is needed for worker-side analysis refunds.

Members who are authorized by the existing product routes consume their
company's allowance. There is no per-user quota. Only owners manage Stripe.
Quota exhaustion never blocks reads, edits, feedback, lifecycle changes,
profiles, Settings, unlinking, or billing reads.

## HTTP contract for frontend Agent C

Entitlement exhaustion returns HTTP **402** with this exact JSON shape:

```json
{"detail":{"code":"analysis_limit_reached","message":"Plan limit reached."}}
```

`detail.code` is one of `free_workspace_limit_reached`,
`organic_account_limit_reached`, `analysis_limit_reached`, or
`idea_generation_limit_reached`. The message is safe display text; the code is
the stable machine key. Fetch `GET /api/companies/{company_id}/billing` after a
successful consuming action or reversal to show authoritative usage. A 402
should offer an owner a Billing path and a member a contact-owner path. Existing
401 authentication, 403 company authorization, and 404 inaccessible child
resource responses take precedence; 402 does not reveal foreign resources.

## Expensive route audit

| Route or producer | V8 treatment |
| --- | --- |
| `POST /api/companies/{company_id}/content/analyze` | Company authorized; new durable jobs reserve analysis. |
| `POST /api/meta/library/analyze` | Verified Meta owner and company member; one linked company required; new jobs reserve analysis. |
| `POST /api/meta/sync`, automatic scheduler/discovery, initial import | `queue_analysis` meters new jobs for a unique linked company; ambiguous or unlinked items defer. |
| `POST /api/meta/library/metrics/refresh` | Metrics only; no content analysis or idea model. |
| `POST /api/meta/companies/{company_id}/recommendations` | Company authorized; reserve before idea model; refund on failed persistence. |
| `POST /api/meta/recommendations` | Unscoped, unpersisted legacy model endpoint returns 410 before model work. |
| `POST /api/videos/{video_id}/recommendations` | Owned video is checked first; legacy unscoped model endpoint returns 410. |
| `POST /api/videos` | Legacy upload and synchronous analysis lacks a company; returns 410 before media work. |
| `POST /api/companies/{company_id}/profiles/{scope}/refresh` | Separate derived company-profile model workflow; existing profile job coalescing/input-hash reuse applies. It does not generate a persisted idea or run content analysis and is outside the two defined usage kinds. |
| `GET` status, content, analysis, ideas, profiles, and billing | Read-only; no usage. |

The 410 routes retain authentication. `GET /api/videos/{video_id}/analysis`
remains an authorized read for existing data. The old single-video recommendation
route checks video ownership before returning 410. No Stripe, model, or provider
internals are included in billing-limit responses.

## Verification and deployment boundary

The tests use a disposable PostgreSQL schema with migrations through 014,
signed auth fixtures, provider/model mocks, concurrency, and the local media
pipeline. No live Stripe, Meta, OpenAI, Supabase, or production database role is
verified by these tests. Confirm production migration 014 and database role
privileges, then exercise real subscription transitions and a complete analysis
and idea generation in staging before launch.
