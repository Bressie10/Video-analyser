# V9 Stage 8.3 — Creative Analysis implementation report

## Scope and provenance

- Exact requested base: `8afe70f7e1ebbfd5b5e256b3d83af5435d6332cf`.
- Implementation commit: `f6ed6efd4fd2262d2edea9e9f635cac5956ec410` on `codex/v9-stage8-creative-analysis`.
- Isolated worktree: `/private/tmp/v9-stage8-creative-analysis`. The main checkout's pre-existing edits were not changed.
- No migration, new identity table, model call, background worker, permanent source-video storage, deployment, V9 tag, or merge to `v9`.

## Identifier and company boundary

`creative_ref` is the existing opaque `meta_library_items.id` UUID for the **video asset**. It is not the provider external ID, the Stage 7.2 pseudonymous `video_ref`, or the stored `videos.id`. The browser never reverses the Stage 7.2 mapping.

Creative Intelligence now projects only `video_ref`, numeric metric value, percentile, and, after `_content` uniquely resolves the authorized ad-to-video edge, `creative_ref` for each eligible member. Its four-field request is unchanged. The public group projection no longer passes internal `provider_id` fields. If content coverage is incomplete, the existing performance group remains visible without `creative_ref` and without a misleading Analysis link.

Every detail, media grant, and media byte request re-checks current company membership, the company's connection, a company-assigned ad, the `meta_ad_assets` edge, and the requested video asset UUID. The stored reader is additionally bound to the asset's connection. A guessed asset UUID outside that relationship returns 404; missing company access returns 403. Multiple assigned ads using one asset retain the asset identity but fall back to a neutral label rather than arbitrarily choosing an ad name.

## Detail contract and evidence behavior

`GET /api/companies/{company_id}/creatives/{creative_ref}/analysis` returns an allowlist: safe label and reference, valid stored duration and resolution, scene number/start/end, transcript text/start/end, OCR text/appearance/disappearance, and a media state. `resolution_required` means a connected Meta credential exists and playback still needs a live provider resolution; `unavailable` means that connection is not currently usable. The response does not include rows wholesale, motion fields, provider IDs/URLs, signed URLs, tokens, ciphertext, prompts, model responses, or raw performance records.

The page has the four approved lanes. Scene ranges use stored scene boundaries; text uses stored OCR intervals; speech uses stored transcript intervals; comparison signals use only validated Stage 7.2 citations in the in-memory handoff. There is no new inference. Empty lane space means no event displayed. Without a valid stored duration, the UI shows timed event lists and no full-duration playhead scale. The Opening 0–3s index is a timed evidence filter, with no hook score. Transcript, OCR, and scene lists use disclosure controls. A disconnected provider still permits stored evidence inspection.

OCR boxes are intentionally omitted. OCR was measured on the normalized processing copy, while playback uses the current provider source; the stored fields do not prove a source-to-normalized coordinate transform. Selected visual moments may show one bounded in-memory capture from the authorized video element after seeking. There is no separate frame store.

## Media delivery and performance

`POST /api/companies/{company_id}/creatives/{creative_ref}/media-access` verifies the normal bearer credential and sets a 15-minute, HttpOnly, same-site, path-scoped cookie containing the already verified application JWT. The native video element then uses same-origin `GET .../media`; every request verifies that JWT and the company-to-asset relationship anew. The server re-resolves the current media location through `meta_media.media_url`, including Meta's identity check. The CDN request carries no provider access-token header. The same `meta_media.validate_url` rule runs before every request and after each redirect; httpx automatic redirects are disabled. Signed provider URLs are never returned to the browser, and the shared Meta log filter redacts provider CDN URLs.

The proxy accepts a single ordinary byte range, requires a real 206 for ranged requests, verifies `Content-Range` and `Content-Length`, and passes through the relevant 206/200, range, length, and MIME semantics. It requests identity encoding and streams raw bytes. Existing 500 MiB and 300-second bounds apply; upstream connect/request timeouts are 10/30 seconds. Responses are private/no-store. Unsupported location, identity mismatch, provider 403/404/410, malformed or ignored ranges, oversized media, and unavailable credentials fail with a safe unavailable response. Playback failure leaves the stored evidence page visible.

The endpoint **re-resolves Meta media on every browser media request**, including seeks. This is a deliberate bounded starting point; there is no cache or persistence. Mocked browser playback and seeking through a 206-capable four-second fixture worked. Actual endpoint startup latency, bytes transferred for an owned Meta playback/seek, provider redirect behavior, source expiry behavior, and repeated-resolution cost are **not measured** because no disposable PostgreSQL-backed owned Meta video was available. Those measurements must be taken before calling live playback reliable; the mock's timings are not provider measurements.

## Comparison handoff and UI

Clicking a comparison thumbnail opens Analysis. A separate smaller control focuses that creative in the Signal Map. The evidence inspector also has an Analysis action for its currently selected citation, so multiple citations for one creative retain the exact selected ref and timestamp. The in-memory handoff carries account label, exact metric and dates, A–F identity, higher/lower numeric group, exact returned metric value, selected signal, validated citation/ref/time, and prior scroll position. The detail page seeks a validated selected citation and shows one compact comparison line. Back navigation keeps the mounted Intelligence result, selected row, filters, and scroll; it does not repeat the expensive request. A direct reload has no handoff and says comparison focus is unavailable, while opening the stored evidence normally. No server-side comparison history was added.

Desktop uses the video as the dominant object, a compact performance strip only when comparison context exists, the synchronized timeline, and a sticky Current Moment rail inside its own column. Selected events seek the player; Enter and Space activate the native buttons. Playback updates scene, OCR, speech, and point-citation emphasis. A selected moment remains inspectable while paused; playback resumes following unless explicitly pinned. Compatible evidence at the selected timestamp is grouped in one rail. Mobile orders player, context, horizontally scrollable lanes, focused evidence, then disclosures. Its focused sheet can close without changing the playhead or timeline position, and the bottom navigation remains exposed. Reduced-motion behavior is respected through CSS.

## Validation

- Stage 6, Stage 7.1/7.2/7.3, Stage 8.1, Stage 8.2, and new Stage 8.3 focused backend tests: **52 run, 48 passed, 4 skipped for disposable PostgreSQL**.
- Focused Creative Intelligence and Creative Analysis browser tests: **15 passed**. They cover native seeking with mocked 206 media, keyboard selection, exact selected-citation handoff and no duplicate intelligence call, unavailable media with retained evidence, no signal, missing transcript/OCR, missing duration, and 390px layout.
- Full frontend run: **332 tests, 315 passed, 17 failed solely because four existing real FastAPI/PostgreSQL integration files require `TEST_DATABASE_URL`**. Those 17 are unverified database paths, not product passes. The database-independent tests in that run passed.
- TypeScript typecheck, Vite production build, Python compilation, and staged `git diff --check`: passed. A targeted secret scan found `token_ciphertext` only in the server-side authorization query; it is not projected into the detail or media response.
- PostgreSQL was not listening on localhost. Disposable `initdb` failed both sandboxed and escalated with `could not create shared memory segment: No space left on device`; the error concerns OS shared memory, not disk space. No DB-backed authorization/migration/browser integration result is claimed.

## Live validation and remaining limits

No real owned Meta video and working disposable database were available for provider validation. Browser playback startup, native range seeking against Meta, re-resolution after URL expiry, and transcript/OCR/scene timestamp sanity against a real source remain unverified. The mock test verifies browser and proxy contract behavior, not actual provider compatibility or semantic accuracy.

The approved concepts that require unsupported data remain absent: per-scene persisted keyframes, OCR boxes over the provider source, and a production Stage 5 semantic-role timeline. A comparison signal appears only from an already validated comparison handoff; it disappears on reload. Refresh-safe performance context was not added because it would enlarge the deterministic comparison scope. These are explicit evidence limits rather than generated placeholders.

D — implementation is complete but real provider validation remains unavailable
