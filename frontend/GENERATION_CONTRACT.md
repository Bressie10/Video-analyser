# V4 Wave 2 Generate Idea frontend

`src/generation/generationApi.ts` owns all paths, wire validation, request serialization and safe errors. `GenerateIdea` uses Wave 1 CompanyProvider, CompanyScopeBoundary, useCompanyQuery and the existing switch guard. CompanyShell supplies a setup action that opens existing management. No second company selector or company storage exists.

## Backend integration assumptions (must reconcile)

Sources: `GET /api/companies/{company_uuid}/content?analysis_status=analyzed&limit=100&order=published_at_desc[&after=cursor]`

Response: `{ items: [{ id: UUID, title: string, platform: 'instagram'|'facebook'|'meta_ads', published_at: ISO timestamp, analysis_status: 'analyzed' }], next_cursor: string|null }`.

The server must authorize the company and return only accessible content. Frontend does not fall back to the unscoped library. It follows all cursor pages, deduplicates IDs, excludes non-analyzed records, sorts by publication time descending (UUID descending tie-break), and resolves the latest 20 for default All mode. "Recent" currently means publication time, not analysis completion time. Manual search/filter runs over this loaded list. All pagination must finish before generation; very large libraries may need server-side search/paging optimization later.

Generation: `POST /api/meta/companies/{company_uuid}/recommendations` (existing V3 route retained pending Wave 2 reconciliation). The active company UUID is explicit in the URL, not duplicated in the strict body. Adapter input is `{ companyId, sourceIds, brief?, targetPlatforms, idempotencyKey }`.

JSON body:
```json
{
  "request_id": "UUID idempotency key",
  "video_ids": ["explicit internal source UUID, 1–20 unique IDs"],
  "generation_brief": null,
  "target_platforms": ["instagram", "facebook"]
}
```

An optional brief is trimmed, blank becomes null, max 10,000 characters. Publishing platforms come from the active company's linked accounts, deduplicated, initially checked. Meta Ads is a source platform only. At least one target is required. No browser API-key field is introduced; generation assumes server-configured credentials.

Success must return persisted `{ id: UUID, company_id: requested UUID, title: nonblank string, concept: nonblank string, script: nonblank string, target_platforms: ['instagram'|'facebook', ...] }`. Extra backend fields are discarded. A provider-only prose response or a response for another company is rejected. Rendering stays on the page and focuses the saved title. This validation identifies a persisted record contract; real database persistence is the backend's responsibility and is not proven by mocks.

Idempotency: synchronous submit lock prevents duplicate calls. An unchanged retry after failure uses the same key (including ambiguous network failure); changed inputs get a new key. A successful generation clears the attempt so another deliberate generation can create a new idea. Backend must replay saved results for that key and must not create a second record. 409 gives safe conflict guidance and a source reload action.

Scope changes unmount local state and abort source/generation requests; render and async scope guards reject stale responses. Generation registers the shell's switch guard. Confirming a switch cancels client waiting; the server may still finish persisting the old-company request. No cross-company result is displayed.

401/404 invalidate scope through the existing CompanyStore. 400/422, 409, service/provider failures and network failures use fixed safe copy; backend/provider details are never rendered. Source loading/error/empty, no company, no publishing platforms and no manual selection have explicit states.

## Validation

`npm run test:generation` covers adapter contracts and real Chromium UI against mocked endpoints. Existing frontend suites remain applicable. `npm run typecheck` and `npm run build` validate compilation. No frontend lint script is configured.

No backend files, history, editing, feedback, lifecycle, publication management or V5 design are implemented here. Live Wave 2 endpoints, provider generation and database persistence still require integration verification once the backend contract is reconciled.

Verified on this branch: 98 unique frontend tests passed (24 generation, 22 company state, 11 company UI, 35 legacy flow, 6 Meta status). Typecheck, production build and diff whitespace checks passed. Chromium screenshots were checked at 320px and 1280px; automated overflow checks also cover 600px. Backend-dependent integration suites were not run for this frontend-only contract change. No lint script is configured.
