# V4 Wave 2 saved ideas frontend

Branch `codex/v4-ideas-ui`, based on local `v4` at `76a4149`.

## Integration

`src/ideas/IdeasPage.tsx` exports `IdeasPage`, mounted in `main.tsx` inside the existing CompanyProvider / CompanyShell / CompanyScopeBoundary. It takes an optional typed `IdeaApi` for integration and fixtures. Mount it under the same providers when adding navigation alongside the separately owned generation page. No generation or source-selection implementation is included.

The global company store is the only company selection source. The page has its own scope boundary as well, resetting filters, selections, drafts and picker state on company/scope changes. Reads use `useCompanyQuery`; writes capture the store scope and combine its abort signal with component lifetime. Completion checks reject stale results even if transport cancellation is ignored. Missing ideas produce local errors rather than clearing company selection.

CompanyShell's opt-in `allowUnlinkedWorkspace` keeps saved ideas accessible after accounts are unlinked, alongside the existing account setup notice. The default remains unchanged for other consumers. Dirty text edits and pending dislike input register with the existing company-switch guard. Save is explicit; Cancel restores the last server-confirmed values. Other detail mutations are disabled while editing. Returning to history requires saving or cancelling changed text. Company-switch confirmation can discard edits. Management keeps the workspace mounted and its guard registered.

## Assumed API contracts — verify with the separate backend branch

All routes, query encoding and wire decoders are isolated in `src/ideas/ideaApi.ts`. The route prefix follows the existing V3 ideas router. These assumptions are **not** proof of the pending Wave 2 backend contract.

| Operation | Assumed route / body |
| --- | --- |
| History | `GET /api/meta/companies/{company_id}/ideas` |
| Detail | `GET /api/meta/companies/{company_id}/ideas/{idea_id}` |
| Edit / lifecycle | `PATCH .../ideas/{idea_id}` with `{title,concept,script}` or `{status}` |
| Feedback | `PUT .../ideas/{idea_id}/feedback` with `{feedback,reason}` |
| Published-content picker | `GET /api/meta/companies/{company_id}/published-content` |
| Link / unlink | `PUT` / `DELETE .../ideas/{idea_id}/publications/{library_item_id}` |

History query: `limit=25`, optional `after`, `search`, `status`, `feedback`, `target_platform`, `created_from`, `created_to`. Filtering is server-side across all results, before pagination. Search is expected to match title/concept/script. Date bounds are inclusive UTC instants covering the selected whole days. Empty filters are omitted. Picker query: `limit=25`, `search`, optional `after`. Both return `{items: [...], next_cursor: string|null}`; cursors are opaque and bound to company/filter scope. Load-more retains earlier pages and filter changes discard prior pagination.

History items: `id`, `title`, `concept`, `status`, `feedback`, `feedback_reason`, `created_at`, `updated_at`, optional `target_platforms`. Details and **all mutation responses** return a full idea adding `company_id`, `script`, `target_platforms`, `publications`, optional `generation_brief`. IDs are internal UUIDs, dates ISO timestamps. Status is `draft|used|published|discarded`; feedback is `none|liked|disliked`. Reason is trimmed/null and sent only for dislike. Details with a foreign company ID are rejected.

Publication records: `library_item_id`, optional `title`, `platform`, `available`, `created_at`. Historical links without live metadata are displayed with neutral fallback wording. `available:false` explicitly means unavailable for live metrics; omitted/null means unverified, not proven accessible. The picker endpoint must return only currently company-authorized published content. Links must be authorized again by the backend on PUT. Historical links never initiate item, provider, evidence, or metrics requests. No external URLs are taken from link data.

The base V3 backend does **not** implement the assumed filter parameters or published-content picker endpoint. Reconcile these in the adapter during Wave 2 integration. Do not ship filter controls against a server that silently ignores the filters. The current edit contract has no version token; the UI surfaces HTTP 409 and preserves drafts but cannot itself prevent concurrent last-write-wins. If the backend adds revision/If-Match semantics, implement them in the adapter.

Only title, concept, script, target platforms, lifecycle, feedback, links, dates and creation brief are exposed. Evidence blobs, request hashes, model/version internals and profile data are not copied into UI records. No profile refresh is present.

Errors use safe local messages, never raw server payloads. 404, 403/archived, 401, 409 and network failures have recoverable views; retry is explicit. Requests use session credentials, no-store and a 20-second timeout. Cancellation cannot guarantee a server-side write was rolled back; revisit/reload shows saved state.

## Validation

- `npm run test:ideas`: **34 passed** (7 adapter tests, 27 browser tests of the real application with intercepted API responses).
- Existing regression command (**74 passed**): `node --test tests/company-state.test.mjs tests/company.test.mjs tests/flow.test.mjs tests/meta-status.test.mjs`.
- `npm run typecheck`; `npm run build`; `git diff --check`.
- Browser coverage includes all filters, pagination, detail, explicit editing/cancel, guard confirmation, feedback variants, reversible lifecycle, multiple links/unlink, unavailable history, failures, conflicts and stale A history/detail/write responses after switching to B. Stale-response tests deliberately ignore fetch abort to exercise commit guards.
- Keyboard focus, modal dismissal/return focus, and overflow checks at 320/600/1280px; screenshots saved under `/tmp/v4-ideas-{detail,picker}-{width}.png`.
- No lint script is configured. No dependencies added. Real backend/database/Meta integration is not tested here because the new backend contract is owned separately. Existing database-dependent integration suites are not part of this frontend-only verification.
