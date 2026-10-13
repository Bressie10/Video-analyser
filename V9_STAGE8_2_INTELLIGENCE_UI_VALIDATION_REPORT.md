# V9 Stage 8.2 — Intelligence UI and real path validation

## Scope and flow

- Base: `be90e9099b2036cc6fa7939511c7768bc0c454b9` on `codex/v9-stage8-intelligence-ui` in an isolated worktree. The main checkout's unrelated `frontend/vite.config.ts` edit was untouched.
- An authenticated user selects a company with the existing workspace selector, opens **Creative Intelligence** in the existing navigation, then selects one linked Meta Ads account, CTR/CPC/CPM/Impressions, and an exact start and stop date.
- One explicit submit sends `account_id`, `metric_id`, `date_start`, and `date_stop` to `POST /api/companies/{company_id}/intelligence` through the existing authenticated fetch helper. The server selects the cohort and owns performance, evidence, and hypotheses. Submission is locked while active; no effect starts the intelligence request.
- No intelligence history, generated intelligence persistence, extra model call, job queue, cache, or new client API framework was added.

## Result presentation

- Performance shows the Stage 7.1 summary, selected metric definition, exact period, ad and peer counts, reference value, median, ratio, percentile, and API-provided standout observations. It does not assign quality labels.
- What differed shows only validated Stage 7.2 observations, group support counts, evidence coverage confidence, timing when supplied, and counterexamples. The section says **Observed difference — not proven cause** once.
- What to test next shows at most three Stage 7.3 experiments with the hypothesis, controllable variable, control, variant, metric, constants, source observation, counterevidence, and limitations. It presents them as experiments to try.
- Citations show a pseudonymous video reference, evidence reference/type, timestamp, and a bounded transcript or OCR excerpt when that text exists in the validated evidence packet. Frame references show the timestamp and reference; raw frames, raw model responses, and prompts are not returned for display.

## Normal degraded states and errors

- No linked Ads account points to existing Settings/Meta connection. A disconnected connection returned by the API points there too.
- An insufficient exact-context cohort explains that more comparable ads are needed. Performance-only output remains visible when analyzed video coverage is insufficient or media is unavailable; no empty recommendations are rendered.
- Model or validation failure keeps the performance section and gives a safe generic explanation. Unauthorized/expired session, invalid date or unsupported metric, unavailable backend, and malformed response use bounded UI text without backend detail or stack traces.
- Loading says **Comparing performance and creative evidence…** and disables inputs and submission; there is no fabricated progress percentage.

## Tests and checks

- Focused mocked Playwright browser tests: **9 passed, 0 failed, 0 skipped**. They cover full output, one and three hypotheses, support with a counterexample, performance-only, insufficient cohort, disconnected/unlinked Meta, media unavailable, loading, safe API errors, malformed success, exact request fields, and no duplicate call on rerender. Desktop and 390 px screenshots were inspected; the checked views had no clipping or overlay. Screenshot artifacts are outside the repo at `/private/tmp/v9-stage82-intelligence-desktop.png`, `/private/tmp/v9-stage82-intelligence-mobile.png`, and `/private/tmp/v9-stage82-intelligence-loading-mobile.png`.
- The final browser/frontend suite excluding four PostgreSQL integration files: **312 passed, 0 failed, 0 skipped**. The new hidden submit form exposed three broad `button[type=submit]` selectors in existing generation browser tests; these now target the generation form. An isolated company-menu detach timeout did not repeat when rerun alone, and the final 312-test run passed.
- Backend Stage 6: 11 passed. Stage 7: 20 passed. Stage 8.2 citation enrichment: 2 passed. Stage 8.1 API tests: 4 collected, all skipped without disposable PostgreSQL.
- Full backend discovery was attempted: 584 tests collected; 8 errored because `TEST_DATABASE_URL` was unavailable and 288 skipped. No non-database assertion failed. The four PostgreSQL browser integration files were likewise not run. Python compilation, frontend typecheck, production build, privacy scan, and `git diff --check` passed. Browser plugin was unavailable; Playwright was used.

## Live Meta and media validation

- No real endpoint call was made. The local configuration names a localhost PostgreSQL database, but no server responded on port 5432. Initializing a disposable PostgreSQL 17 cluster failed inside the sandbox with `Operation not permitted` for shared memory and outside it with `No space left on device` for a shared memory segment. Docker was unavailable. Therefore no authorized owned account or qualifying six-ad cohort could be established safely from local data.
- The exact reporting context, six analyzed ad/video associations, real Stage 7.2 citations, and real Stage 7.3 hypotheses could not be inspected. The critical question of whether Meta can re-resolve and download all six analyzed source videos remains unverified. No media, provider response, token, or customer identifier was committed.
- Real total wall time, six-media download time, Stage 7.2/7.3 latency, model calls, and token counts are unavailable. The successful endpoint response already carries bounded model call metadata and total elapsed time; Stage 8.2 also records the media-download portion. No cache or queue decision is justified without a real measurement.
- Evidence accuracy classification (**supported / questionable / unsupported**) and hypothesis usefulness review (controllability, control/variant clarity, fidelity to the observation, causal language, creator clarity) require the blocked real cohort. Mocked checks are contract tests, not an accuracy review.

## Remaining blockers before V9 release

1. Restore access to a disposable PostgreSQL instance, then pass the Stage 8.1 API and full backend database suite without skips.
2. Run one owned-account CTR comparison for an exact window with at least six comparable observations and six analyzed video associations. Inspect every cited frame, OCR item, transcript excerpt, timing claim, support count, counterexample, and resulting experiment against the source media.
3. Record aggregate source-media re-resolution success/failure and measured timing and token counts. Complete the manual evidence and hypothesis sanity reviews before release audit.

D — live validation could not be completed; code is UI-ready but provider behavior remains unverified
