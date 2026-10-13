# V9 Stage 8.2 — Creative Intelligence implementation and validation

## Scope and design

- Branch: `codex/v9-stage8-intelligence-ui`, based on Stage 8.1 `be90e9099b2036cc6fa7939511c7768bc0c454b9`. Implementation commit: `e2fc45a07c58ec5e9b7c10fa289f4f016ceccad4`.
- Implemented the latest Creative Intelligence v8 comparison concepts in `V9_UI_DESIGN_DIRECTION.md` and `design/creative-intelligence/v8/`. These exact approved references were copied into this branch without changing their originals in the main checkout. Earlier large-card concepts were not used. The approved Creative Analysis designs in `design/single-creative-review/v2/` remain for Stage 8.3; no single-video route or playback analysis was built.
- The page now uses a compact account/metric/exact-date toolbar; a dark Stage 7.1 performance strip with six marker positions, reference value, median, ratio, percentile and peer count; a two-cohort A–F creative strip; a dense Creative Signal Map; compact control/variant experiments; and a modal Evidence Trace. The 1440px browser capture shows controls, performance, all six creatives, the map, and the first experiment in the opening viewport. A 390px capture has no document overflow; creatives scroll horizontally and the selected signal expands into six compact lanes.
- Higher/lower means **numeric selected metric**, not creative quality. Uncited signal/video intersections show `?` for no validated citation. The UI never infers absence from sparse sampled frames and never constructs creative claims or support counts in the browser. Selecting a signal marks support and counterexamples across the creative strip; selecting a creative focuses cited map rows. Experiments link back to the source signal.

## API and media boundary

- The authenticated browser request remains `POST /api/companies/{company_id}/intelligence` with exactly `account_id`, `metric_id`, `date_start`, and `date_stop`; it uses `cache: 'no-store'`, scoped cancellation and a synchronous duplicate-submit lock. Cohort selection, performance, differences, citations and hypotheses remain server-owned. No new model call, media job, cache, queue, history or persistence was introduced.
- The only response enhancement is optional `creative_previews`: at most six JPEG stills from frames Stage 8.1 already sampled from its authorized, re-resolved source media. Each is capped at 320px and 64 KiB; no extra provider fetch or permanent storage is added. Each preview entry contains a pseudonymous video reference, sampled frame reference, timestamp and base64 JPEG, never a provider URL, token, temporary path or full video. Failed preview encoding leaves intelligence intact. Missing previews use a neutral frame fallback.
- Evidence Trace permits keyboard/touch citation switching, exposes counterexamples, exact timestamps and bounded transcript/OCR excerpts, and groups citations at the same video timestamp into one cited moment. A preview is called an **exact source frame** only when its frame reference matches a cited frame. Otherwise it is explicitly labeled a creative preview, not proof of that citation. Prompts, raw model responses and internal provider IDs are not rendered.

## Degraded results and recovery

- No linked Ads account: the form is hidden and Integrations is the direct next action. Disconnected Meta, invalid selection/date, expired session, unavailable backend and malformed response use bounded product copy without provider/internal errors.
- Insufficient cohort: no invented performance, map or experiment. When performance is valid but media, coverage or Stage 7.2 fails, valid performance remains and the absent reasoning is explained. Stage 7.3 failure retains validated differences and removes empty experiment cards. Limitations and the single observational-association notice are secondary to the analytical result.

## Checks

- Focused Stage 8.2 browser tests: **9 passed** after the JPEG fixture was added. They cover exact four-field request, six markers/creatives, selected signal, creative focus, support/counterexample treatment, Evidence Trace with exact frame and same-moment text, one/three experiments, performance-only, media/model failure, insufficient cohort, disconnected/unlinked Meta, loading lock, safe API errors, malformed response, desktop and 390px rendering.
- Stage 6.1, 6.2, 7.1, 7.2, 7.3, 8.1 and 8.2 focused Python suite: **35 passed, 4 Stage 8.1 database cases skipped**. The new preview tests verify bounding, image downscaling, restricted response fields and unreadable-image fallback.
- Frontend typecheck and production build passed. Python compilation and `git diff --check` passed. A source scan found no browser-side provider IDs, tokens, temporary paths or raw model data; existing server-side provider IDs remain confined to authorized media resolution.
- An unrestricted `npm test` run reported **311 passed, 18 failed**: 17 database-dependent tests stopped at their missing `TEST_DATABASE_URL` gate; one new evidence test ran before its fixture file existed. That focused test subsequently passed. The complete frontend suite excluding four database-integration files passed: **312 passed, 0 failed, 0 skipped**.
- Browser screenshots used for layout inspection: `/private/tmp/v9-stage82-intelligence-desktop.png`, `/private/tmp/v9-stage82-intelligence-mobile.png`, `/private/tmp/v9-stage82-evidence-desktop.png` and `/private/tmp/v9-stage82-evidence-mobile.png`. These are mocked contract views, not live-provider evidence.

## Database, live provider and performance limits

- No PostgreSQL server answered on localhost 5432 or 55448. The existing disposable cluster at `/private/tmp/cm-v9-stage8-pg` could not start, including outside the sandbox: PostgreSQL reported `could not create shared memory segment: No space left on device`. Stage 8.1 database/API tests and database-backed browser integration therefore remain unverified, not passing.
- No owned Meta account with a qualifying exact-context six-ad cohort was available through this environment. Real source-media re-resolution, preview display, validated Stage 7.2 references, counterexamples and Stage 7.3 hypothesis grounding were not inspected against customer source media. Evidence classifications (supported/questionable/unsupported) remain unavailable. The implementation must not be treated as provider-validated.
- Real endpoint wall time, media download time, Stage 7.2/7.3 model latency, call count and safe token metadata are **unavailable**. The existing response can carry bounded timing/call metadata, but no queue or cache decision is justified without real measurements.

## Remaining validation before release

1. Restore disposable PostgreSQL and run the Stage 8.1 API plus database-backed frontend suites.
2. Run an owned-account comparison with six analyzed video associations in one exact metric/date context. Verify each sampled preview and cited frame/text/time against the source media, including counterexamples.
3. Record media re-resolution success and request/model timings before judging responsiveness or cost.

D — implementation is complete but real provider validation remains unavailable
