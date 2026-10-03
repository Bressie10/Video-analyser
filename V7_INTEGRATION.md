# ContentMetric V7 integration

## Provenance and conflict resolutions

Base: `0758c39e09acdc7b33bfcf8305c1067c1ef682bd` (V6 integration).
Cherry-picked in order: `ec53d023287a3a8b955adbc1a2728f9a71f9a0e3`
(onboarding backend), `0d639b5d010921268bb81cbf9aaf66b9dac6aaec`
(activation surfaces), and `a2b9741ffa439c46d1d5b065f297c2df275f8bff`
(onboarding frontend). Git reported no textual conflicts; the frontend pick
automerged `frontend/tests/auth.test.mjs`.

The meaningful integration conflict was behavioral: activation Content showed
analysis status without an action to start it, while onboarding directed users
there to analyze their first item. V7 adds one owner-only, company-scoped
`POST /api/companies/{company_id}/content/analyze` action. It checks V6
membership, an owned Meta connection, and item access, then delegates to the
existing `meta_library_repository.new_batch` analysis queue. Organic video and
reel items are eligible; Ads remain on existing semantics. The Content row
exposes Analyze/Retry analysis. No second analysis pipeline or migration was
added. Generate's mounted source query refreshes when Content analysis status
changes, and its default target selection becomes available when the first
publishing account is linked after Generate has mounted.

The frontend handoff treated every missing onboarding row as a first login.
The integrated UI shows the welcome only when progress is 0 and welcome has
not been handled; an existing V6 user with real partial progress goes straight
to the app and persistent reminder. A guided completion state remains visible
until acknowledged even if Overview refreshes. The backend response contract
and all five independent step flags remain unchanged.

## Architecture and product behavior

`GET /api/me/onboarding` is authoritative. Its exact response fields are
`company_id`, `welcome_seen`, `skipped`, `progress`, `complete`, `next_step`, and
`steps` with `workspace`, `meta`, `account`, `analysis`, `idea`. Each true step
contributes 20%; the client renders the received percentage and flags without
deriving a second progress value. The response is private and non-cacheable.
All onboarding requests use V6 `apiFetch` and a Supabase Bearer session; no
raw onboarding fetch, stored JWT, service role, or completion mutation exists.

`POST /welcome` stores the welcome choice. `POST /skip` stores a navigation
choice, never functional completion. The normal Overview, Content, Generate,
Ideas, and Settings remain accessible at any time. The Overview reminder and
shell indicator remain while backend `complete=false`; Continue setup resumes
the guide. At 100% during guided setup, Overview shows “You're ready to go”
until acknowledged. If real state later regresses, the reminder returns.

The onboarding company is separate from the active company selector. `PUT
/api/me/onboarding/company` runs only for an explicit guided choice or a
company created from guided setup. Ordinary active-company changes do not
write it. `GET` can return a read-only derived fallback when the persisted
anchor is missing, archived, or inaccessible, so the UI labels it a suggested
setup workspace and offers an explicit picker. Guided actions switch to the
setup company through the existing guarded company switch. Backend membership
validation and fallback selection prevent a stale anchor from granting access.

Meta setup uses V6 authenticated JSON initiation at
`/api/meta/connect?response_mode=json`, then the existing popup callback and
owned connection. A publishing account step requires Facebook or Instagram
linked to the onboarding company; Meta Ads alone does not count. Settings
retains owner-only link controls. Content status is refreshed after analysis
requests and when the user chooses Refresh analysis status; a completed read
refreshes onboarding and Generate sources. Generated ideas refresh onboarding
only after the existing API returns a persisted idea. The Ideas page continues
to show saved history or its useful empty state independently of guided mode.

Page-level Content states cover no publishing account, linked but empty,
unanalysed, processing, and failed items. Generate shows its analysis
prerequisite until usable sources exist. Ideas shows an empty-history action
or populated history. These states remain useful after Skip for now.

## Refresh and isolation

Onboarding refreshes on initial authenticated mount, return to a page (including
Overview), explicit onboarding mutations, company creation, Meta connection
status changes, account link/unlink, Content analysis state changes, persisted
idea generation, and user-initiated Refresh progress. The Content read and
onboarding provider reject stale responses; the existing company scope and
generation guards remain. No polling loop was added for onboarding. A user
can refresh Content after asynchronous analysis, and tab visibility triggers
one onboarding refresh when returning.

AuthGate remounts the workspace on identity change or logout. The V7 browser
flow confirms User B sees 0% and no User A company/idea after User A reaches
100%, then User A recovers backend-derived 100%. A provider cookie belonging
to User A yields a safe `/api/meta/test` 403 for User B without signing B out.
401 continues bounded V6 auth recovery; 403 remains a permission state; stale
or archived onboarding company selection returns to an accessible suggestion.

## Database and verification boundary

Migration `013_onboarding_state.sql` follows 001–012 and stores only UX choices.
The backend tests exercise fresh 001–013, populated V6 001–012 then 013,
preserved historical rows, no synthetic completion, rollback behavior, and
default-deny RLS. `GET` uses one bounded SQL statement over the signed user's
memberships and does not request progress once per company. Production FastAPI
still requires a table-owner or `BYPASSRLS` database role; browser Data API
grants for application tables must remain disabled or denied.

Local browser integration uses real React, FastAPI, PostgreSQL, company APIs,
onboarding APIs, analysis batch enqueue, and idea persistence. External Meta
authorization, provider responses, model generation, and the asynchronous
media worker completion are controlled fixtures. The backend media suite tests
the real local processing path separately. The V7 browser test includes
0→20→40→60→80→100, completion acknowledgement, User B isolation, User A
return, and Meta regression to 80 with unrelated steps retained.

## Remaining deployment checks

Live Supabase sessions, production database role/grants and migration history,
live Meta OAuth and callback domain, provider account discovery, real provider
content, live model generation, worker scheduling, and production deployment
were not exercised locally. Smoke-test these in a staging deployment with a
new user and a populated V6 user before release. Confirm 013 applies after
the existing migration history, provider callbacks return to the configured
origin, owner-only linking is enforced, asynchronous analysis reaches current
completion, a saved idea reaches 100%, and A→B→A isolation holds. Check mobile
layouts at 1440, 1024, 768, 390, and 320 pixels and inspect console/network
errors. Do not infer live readiness from local provider mocks.
