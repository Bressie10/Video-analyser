# V4 integrated generation

`src/generation/generationApi.ts` implements the real company content and persisted
idea contracts. Wave 1 CompanyProvider remains the only source of company identity.

Default source resolution makes one request:
`GET /api/companies/{company_id}/content?analyzed_only=true&limit=20&order=desc`.
It decodes `library_item_id`, `display_title`, `published_at`, `platform`, `analyzed`
and `next_offset`. Manual mode follows offset pages of analyzed content, deduplicates
library IDs and allows 1–20 selections. Manual search/platform filtering operates
on these loaded, already company-authorized rows. Nullable publication dates are
supported; the backend orders null dates last. No backend auto-selection mode exists.

Generation uses `POST /api/meta/companies/{company_id}/recommendations` with:

```json
{
  "request_id": "fresh UUID for a new intended generation",
  "video_ids": ["library_item_id UUID, NOT video_id"],
  "generation_brief": null,
  "target_platforms": ["instagram", "facebook"]
}
```

The optional brief is trimmed and bounded to 10,000 characters. Linked Instagram
and Facebook targets start checked; at least one is required. Meta Ads is never
a target. Zero analyzed sources, loading, missing targets and missing manual
selection disable generation with setup/empty guidance.

A synchronous lock prevents duplicate submits. An unchanged failed request retains
its UUID for retry, including transport uncertainty; changed inputs and a new
attempt after success get fresh UUIDs. Successful responses must have a persisted
idea UUID, the requested company UUID and structured title/concept/script/targets.
The result stays on the page; saved history refreshes without discarding an open
idea editor. Backend/provider internals are not rendered.

Scope boundaries reset local selections/results, combine abort signals and check
scope identity before committing results. The switch guard stays registered during
generation, including while management is open. Confirmed switching cancels waiting;
a server may still persist the original company's request, which remains in that
company's history. Request keys survive retries within the mounted workflow, not
browser reloads or confirmed scope changes.

`npm run test:generation` uses real Chromium with controlled HTTP fixtures and
adapter tests. `npm run test:wave2-integration` uses real FastAPI/session/PostgreSQL
and a mocked model boundary. See [integration report](../V4_WAVE2_INTEGRATION.md)
for complete verification and limitations.
