# V4 company management API

Requires migrations 001–010 and the existing authenticated Meta session cookie
(scoped to `/api`). No new migration, credentials, connection ID payload, or
membership system is required. A company is created under the authenticated
connection with a name only; account linking is optional and always manual.

All IDs below are internal UUIDs. These routes use the real 006 ownership
repository, including profile invalidation and the 010 integrity constraints.
Existing V2 routes and V3 profile/idea routes are unchanged.

## Routes

| Method | Route | Body / result |
| --- | --- | --- |
| GET | `/api/companies` | `{ "companies": [Company] }`; active only by default |
| GET | `/api/companies?include_archived=true` | Active and archived companies for management |
| POST | `/api/companies` | `{ "name": "Company name" }`; returns Company, HTTP 201 |
| GET | `/api/companies/{company_id}` | Company, including when archived |
| PATCH | `/api/companies/{company_id}` | `{ "name": "New name" }`; returns Company |
| POST | `/api/companies/{company_id}/archive` | No body; returns Company |
| POST | `/api/companies/{company_id}/restore` | No body; returns Company |
| GET | `/api/meta/accounts` | `{ "accounts": [AvailableAccount] }` |
| PUT | `/api/companies/{company_id}/accounts/{account_id}` | No body; links account, returns Company |
| DELETE | `/api/companies/{company_id}/accounts/{account_id}` | Unlinks account, returns Company |
| GET | `/api/companies/{company_id}/accounts/{account_id}/ads` | `{ "ads": [AssignableAd] }` |
| PUT | `/api/companies/{company_id}/ads/{ad_item_id}` | No body; assigns ad, returns `{ "ok": true }` |
| DELETE | `/api/companies/{company_id}/ads/{ad_item_id}` | Unassigns ad, returns `{ "ok": true }` |
| POST | `/api/companies/{company_id}/ads/{ad_item_id}/reassign` | `{ "target_company_id": "UUID" }`; returns `{ "ok": true }` |

Successful responses are HTTP 200 unless specified above. Names are trimmed,
required, and limited to 200 characters. Request bodies reject extra fields.

## Response shapes

```typescript
type Account = {
  account_id: string;
  platform: 'facebook' | 'instagram' | 'meta_ads';
  display_name: string;
};
type Company = {
  company_id: string;
  name: string;
  archived: boolean;
  accounts: Account[];
};
type AvailableAccount = Account & {
  organic_owner: null | {
    company_id: string;
    name: string;
    archived: boolean;
  };
};
type AssignableAd = {
  ad_item_id: string;
  display_name: string;
  assigned: boolean; // true only for the company in the route
};
```

The account list reads locally discovered accounts for the current connection;
it does not call Meta or discover additional accounts. An organic owner may be
archived and continues to reserve its account. Ads accounts have no exclusive
owner; their `organic_owner` is always null. Use each Company's `accounts` to
show its links. Legacy provider-ID/URL labels fall back to generic friendly names.

The ad selector requires an active company and a linked Ads account. It includes
only unassigned ads and ads already assigned to that company. Sibling-company ads
are omitted entirely, even if they share a creative. It returns selection metadata
only: no metrics, creative edges, content access, provider IDs or provider URLs.
Linking an Ads account does not grant access to any ad's content or metrics.
Use the source company's selector to choose an assigned ad for reassignment;
reassignment requires both companies to be active and the destination already
linked to the ad's Ads account. It commits atomically or leaves ownership intact.

Repeated links, assignments to the same owner, unlinks and unassignments are
idempotent. Unassigning through a different company never removes the actual
owner's assignment. Ads-account unlink returns 409 while that company's assigned
ads remain. Organic-account claims return 409 until the existing owner unlinks.
Archive retains all records/links/assignments. Archived companies allow management
reads and restore; rename and ownership mutations return 404 until restored.
Repeated archive/restore requests are idempotent.

## Authorization and errors

Authentication, the repository mutation, profile invalidation and response reads
share one transaction. Connection and session locks remain held through commit;
write requests take exclusive locks up front to serialize ownership changes.

- **401**: missing, expired or revoked session; disconnected or expired connection.
- **404**: unknown/foreign company or resource; archived company for an active
  operation; missing linked Ads account or reassignment source ownership.
- **409**: ownership conflict, destination Ads link missing, or unlink blocked by ads.
- **422**: invalid UUID, name or body shape.
- **503**: storage/configuration failure, with a generic error and no database detail.

Errors use `{ "detail": ... }`, consistent with existing FastAPI APIs. Management
responses (including handled errors) use `Cache-Control: private, no-store`.
No company selection is stored server-side. Pass the selected company's UUID on
each scoped request and send the existing session cookie. Lists are currently
unpaginated, matching the underlying ownership repository.
