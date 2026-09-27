# V4 integrated saved ideas

`IdeasPage` is mounted alongside generation and company content under Wave 1
CompanyProvider/CompanyShell. CompanyScopeBoundary resets filters, selection,
drafts and picker state. Reads and writes capture the validated active company,
abort on changes and reject late completions even if transport abort is ignored.
Saved history remains available after accounts are unlinked. Archived companies
are inaccessible under the backend's existing read and mutation policy.

All paths below start with `/api/meta/companies/{company_id}`:

| UI operation | HTTP contract |
| --- | --- |
| History | `GET /ideas?limit=25[&after=UUID]` |
| Detail | `GET /ideas/{idea_id}` |
| Explicit Save | `PATCH /ideas/{idea_id}` with `{title,concept,script}` |
| Lifecycle | Same PATCH with `{status}` |
| Feedback | `PUT /ideas/{idea_id}/feedback` with `{feedback,reason}` |
| Publication picker | `GET /publication-options?limit=25[&after=UUID]` |
| Link / unlink | `PUT` / `DELETE /ideas/{idea_id}/publications/{library_item_id}` |

History sends optional `search`, `status`, `feedback`, `target_platform`,
`created_from`, `created_to`. Filtering occurs server-side before pagination.
Dates use UTC midnight inclusive and next-day midnight exclusive. Pagination
retains filters; changing filters resets the cursor chain. The publication picker
has no search control because its backend contract does not offer search.

History parses `{items,next_cursor}`. Detail/mutations parse full saved ideas.
The picker maps `{id,label,platform,content_type,published_at}` to display options;
its `id` is a library item UUID. Historical associations contain only
`{library_item_id,created_at}` and display neutral titles with unverified live
availability. They never authorize metadata/metrics requests. Multiple links and
removal are supported; association does not imply posting, automatic matching or
causality. Backend authorization is rechecked when adding links.

Editing requires Edit and Save. Cancel restores the last server-confirmed values;
there is no autosave. Dirty edits register the company-switch guard. Request errors
preserve the draft. There is no revision/version/If-Match contract: simultaneous
multi-client editing remains last-write-wins. No speculative migration was added.

Feedback supports liked, disliked (optional reason), and clearing to none. Only
disliked can retain a reason. Lifecycle transitions between draft, used, published
and discarded are reversible; Discarded is visually separated. Evidence blobs and
model/request internals are excluded from the ordinary detail projection.

401/404/409 and service failures have safe messages. Existing profile refresh is
under Manage companies, using active-company `POST /api/companies/{company_id}/profiles/shared/refresh`
with `Idempotency-Key`; 202 means queued, not completed. It is not on the idea page.

See [integration report](../V4_WAVE2_INTEGRATION.md) and
[backend API](../backend/IDEA_API.md) for verification and remaining limitations.
