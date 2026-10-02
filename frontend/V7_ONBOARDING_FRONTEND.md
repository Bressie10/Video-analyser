# V7 onboarding frontend

## Components and lifecycle

`src/onboarding/onboardingApi.ts` calls the V7 endpoints through the existing `apiFetch` helper. `OnboardingProvider` lives inside V6 `AuthGate` and `CompanyProvider`, so its state is created only after authentication and accessible-company validation. The auth gate remounts the whole workspace on identity change and removes it on logout. The provider waits for the first onboarding GET before mounting the app; it shows a loading status instead of flashing a welcome screen.

`OnboardingScreen` renders the first-login welcome, guided setup, compact Overview reminder, and one-time completion message. `AppShell` renders a small Finish setup indicator when welcome has been seen and the backend reports incomplete setup. The existing V5 shell, navigation, company selector, Settings, Content, and Generate pages remain in place. Setup mode is a workspace screen on Overview; navigation stays available.

## API contract and authority

The client assumes `GET /api/me/onboarding` returns `company_id`, `welcome_seen`, `skipped`, `progress`, `complete`, `next_step`, and the five boolean step flags. The client sends `POST /api/me/onboarding/welcome`, `POST /api/me/onboarding/skip`, and `PUT /api/me/onboarding/company` with `{ "company_id": "<uuid>" }`. It never derives progress or completion from local actions. After each mutation it fetches the server state again. All calls carry V6 Bearer authentication through `apiFetch`; the browser has no second auth client.

The existing V6 401 handling remains authoritative. Onboarding 403 and 404 show safe copy and refresh accessible companies; 5xx leaves normal navigation available with Retry setup. Raw backend responses are never shown.

## Modes, skip and existing users

An incomplete first response with `welcome_seen=false` opens welcome. Start posts welcome, refreshes, and enters guided setup. Skip posts welcome first if needed, posts skip, refreshes, and opens the normal app. `skipped=true` never means complete. Continue setup opens the guided screen again. Users may navigate away during setup and return through Overview or the shell indicator.

An existing V6 user with `complete=true` sees the normal app directly. A partially configured existing user sees the persistent reminder without a blocking welcome when `welcome_seen=true`. The completion message appears only when an active guided session receives `complete=true`; leaving it removes the reminder. If the backend later reports incomplete, the reminder returns.

## Company and workflow integration

Company creation stays in the existing Settings form and CompanyStore. After successful create and guarded selection, the shell reports the created UUID, onboarding sends the company PUT, then refreshes. When there are multiple accessible companies and no stored onboarding company, setup requires an explicit choice. The onboarding company is separate from the normal active-company selection. A normal selector change never sends an onboarding company PUT. If the chosen setup company differs from the active one, the guided action uses the shell's guarded switch.

Meta uses the existing `MetaConnection` popup and authenticated JSON initiation. A connection status transition refreshes onboarding. The account step opens existing Settings Content ownership controls; a successful link or unlink refreshes onboarding. The analysis and idea steps navigate to the existing Content and Generate workflows. Navigation, tab visibility, and successful idea save refresh progress. A Refresh progress button covers background analysis or delayed provider/account events. Meta Ads alone is never described as completing the organic account step.

## Layout and accessibility

The screen uses V5 tokens and shared Button, Panel, Badge, Alert, and LoadingState. It has one shell h1 and semantic section headings, labelled company selection, text plus icon step states, a labelled progressbar with percentage text, keyboard buttons, and visible focus. At 768px the setup columns stack. At 390px and 320px primary controls wrap or fill the width. Browser tests cover 1440, 1024, 768, 390, and 320px.

## Verification boundary

`tests/onboarding.test.mjs` uses deterministic authenticated API responses. It does not prove the V7 backend exists or verify live Supabase, Meta, or provider callbacks. The frontend expects the backend to persist and compute every setup field and to return safe authorization responses.
