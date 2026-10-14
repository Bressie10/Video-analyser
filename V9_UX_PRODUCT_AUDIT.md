# V9 UX and product shell audit — corrected for Stage 8.2

**Audit date:** 13 October 2026  
**Actual release candidate inspected:** `/private/tmp/v9-stage8-intelligence-ui`, branch `codex/v9-stage8-intelligence-ui`, clean worktree at commit `b7e085b89d412e189bcedf4c6c5d0e533f31651d` (`origin/codex/v9-stage8-intelligence-ui` pointed to the same commit when checked). Its parent is `be90e9099b2036cc6fa7939511c7768bc0c454b9`.  
**Separate pending fix inspected:** uncommitted billing/workspace changes in `/Users/ultanbreslin/Downloads/Video_Analyzer` on `v9` at `be90e90`. They are **absent from `b7e085b`**. Because this task prohibits application-code changes, this report evaluates their expected UX impact separately; it does not treat them as part of the release candidate. The report is stored in the main checkout for continuity with the requested filename.

## 1. Executive summary

The previous audit used the older main checkout and incorrectly said Creative Intelligence had no mounted frontend. Stage 8.2 **does** mount `#intelligence` in the authenticated shell. A user with a linked Meta Ads account can choose an account, metric and exact dates, run an on-demand comparison, and receive performance context, cited creative differences and experimental hypotheses when evidence permits. The screen also has performance-only and abstention states. That changes both the product map and the ranking of redesign work.

The remaining product-shell problem is fragmentation: signed-out users land on a sparse login form; first-time setup sends users into a long mixed Settings page; integrations, company linking, ownership and billing remain hard to locate; active workspace and inspected company can diverge; and the new intelligence result relies on specialist terms without fully explaining how its comparison was selected. The current six-item sidebar is functional but gives equal weight to destinations that belong to different levels of the product.

**Evidence boundary:** This is a current-source audit plus inspection of Stage 8.2's existing mocked browser screenshots and validation report. No fresh live Meta/Stripe/Supabase/production flow or user study was run. The Stage 8.2 report records passing mocked UI checks, but expressly says live source-media availability and result accuracy were not verified. Recommendations below are design proposals, not implementation decisions.

## 2. Existing product map

| Surface | Current Stage 8.2 behavior | Evidence in release candidate |
|---|---|---|
| Public entry | Signed-out `/` redirects to `/login`; no landing page, product preview, pricing or help/docs page. | `frontend/src/main.tsx`, `auth/AuthGate.tsx` |
| Public legal | `/privacy`, `/terms`, `/data-deletion` render without auth. “Back to ContentMetric” leads signed-out visitors to login. | `main.tsx`, `pages/LegalLayout.tsx` |
| Login/signup/reset | `/login`, `/signup`, `/forgot-password`, `/auth/callback`; email/password, Google, confirmation and reset states. Centered brand/form panel and legal links. | `auth/AuthPages.tsx`, `auth/auth.css`, `auth/authClient.ts` |
| Session/access | Auth loading and recovery; protected API; expired-session signout; logout-error retry; company-access validation before app mount. | `auth/AuthProvider.tsx`, `AuthGate.tsx` |
| Workspace selection | Header picker lists accessible active companies and Manage companies. Valid stored selection is restored; a fresh browser can have none selected. | `CompanySelector.tsx`, `company/companyStore.ts` |
| Workspace creation/management | Settings creates, renames, inspects, archives and restores companies. Inspected company can differ from active workspace. | `CompanyManagement.tsx`, `CompanyShell.tsx` |
| Authenticated shell | Desktop sidebar: Overview, Content, **Creative Intelligence**, Generate, Ideas, Settings. Mobile hamburger holds those links; account email/signout sit at sidebar bottom. | `shell/navigation.ts`, `shell/AppShell.tsx`, `shell/shell.css` |
| Home/Overview | For a linked active workspace: linked platforms, analyzed count, recent content and ideas, Generate CTA. Otherwise onboarding or workspace/connection empty state. | `shell/WorkspaceOverview.tsx`, `CompanyShell.tsx` |
| Onboarding | Welcome/guided/reminder/complete states: workspace → Meta connection → publishing account → analysis → idea. It does not introduce Creative Intelligence or an Ads-account path. | `onboarding/OnboardingScreen.tsx` |
| Content and video analysis | `#content`: published-content filters, status badges, owner-only Analyze/Retry on eligible non-ad items. No mounted per-video analysis detail in the main app. | `company/CompanyContent.tsx`, `content/ContentList.tsx` |
| **Creative Intelligence** | `#intelligence`: linked Meta Ads account, CTR/CPC/CPM/Impressions, start/end dates, explicit Run action; performance → observed creative differences with evidence/counterexamples → experiments when returned. No result history or share route. | `intelligence/IntelligencePage.tsx`, `intelligence/intelligence.css`, `main.tsx` |
| Idea generation | `#generate`: latest or manually selected analyzed sources, publishing target, optional brief, saved title/concept/script. | `generation/GenerateIdea.tsx` |
| Saved ideas | `#ideas`: search/filters, idea detail/edit, feedback, lifecycle state and manual publication links. Detail state has no distinct URL. | `ideas/IdeasPage.tsx` |
| Meta/integrations | OAuth connect/reconnect/status under Settings; per-workspace publishing/Ads account links and ad assignment under Content ownership. | `MetaConnection.tsx`, `CompanyManagement.tsx` |
| Billing | Plan/usage/checkout/portal inside Settings for inspected company. Limit notices can point only to generic Settings. In this RC, billing is **hidden for archived inspected companies**. | `billing/BillingUI.tsx`, `CompanyManagement.tsx`, `CompanyShell.tsx` |
| Settings/profile | One long page: General, Billing, Integrations, Content ownership, AI & Analysis, Company management, archive/restore. “Company intelligence” under AI & Analysis is a **profile refresh**, separate from the Stage 8.2 comparison. No personal account settings screen. | `CompanyManagement.tsx`, `company/ProfileRefresh.tsx`, `auth/AuthGate.tsx` |
| Legacy video UI | `VideoLibrary`, `MetaBrowser`, `useMetaLibrary` remain in source/test fixtures but are not mounted from current `main.tsx`. | `VideoLibrary.tsx`, `MetaBrowser.tsx`, `tests/legacyFixture.tsx` |

**State coverage:** The UI contains auth loading/invalid-link/configuration/confirmation states; workspace load/access/no-selection/archived states; Meta checking/disconnected/popup failure states; onboarding reminder and completion; Content empty/filter/queued/failed states; intelligence unlinked/loading/performance-only/insufficient cohort/disconnected/media or model failure states; idea source/result/error states; billing loading/error/return/limit states; and unsaved-switch confirmation. These states exist, though some send users to generic Settings and require them to find the exact prerequisite.

## 3. Current user journeys

Counts represent visible user actions or destination changes on a typical happy path, excluding provider/email screens and waiting for discovery, analysis or media. They are approximate because eligibility and existing accounts vary.

| Journey | Actual Stage 8.2 path and steps | Confusion, hidden actions or dead ends |
|---|---|---|
| **A. Brand-new user** | `/` → redirect to Login → Signup → submit → possible email verification → sign in → Start setup → Create workspace/Settings → name/Create → Overview → Connect Meta popup → Settings/Content ownership link Instagram or Facebook → Content/Analyze eligible item → Generate/submit saved idea. Roughly **12–15 actions**, plus confirmation/OAuth. | The first useful result in onboarding is an idea, not Creative Intelligence. Workspace creation opens “Manage companies.” Meta connection does not itself link an account. The link step lands at general Settings. Source discovery and analysis may not complete immediately. No product explanation before signup. |
| **B. Returning user** | Sign in if needed → validated stored workspace or manual picker → Overview → choose one of six sidebar destinations. About **1–3 actions** with restored selection, **3–5** without it. | Browser-local workspace selection can be absent. Overview does not highlight intelligence as a next action. Generate and Ideas split one creation flow; Settings mixes administration and integration. |
| **C. Workspace owner** | Create: picker/Settings → create form → Create (**3 actions**). Switch: header picker → workspace (**2**). Archive: Settings → existing/archived disclosure → inspect → danger zone/Archive (**4–5**). Integrations or Billing: Settings → section button/scroll (**2–3**). | Header active workspace can remain A while Settings inspects B. Billing belongs to B, while AI & Analysis profile refresh uses active A. Archive is deep below other settings. A quota upgrade link can open Billing for A even if the limit requires upgrading another owned Free workspace. |
| **D. Creative Intelligence user** | Sign in/session → choose workspace → open **Creative Intelligence** → if no linked Ads account, Settings/Integrations: connect Meta and link Ads account; account-specific ad assignment may also be required → return to Intelligence → choose Ads account, metric, start/end date → Run → inspect performance, differences, experiments or abstention. **5 actions** for an already ready workspace; roughly **9–13+** when Meta and ownership need setup, plus provider steps. | The UI correctly exposes the destination and result. It does not show readiness for exact-context observations, sufficient comparable ads or six available analyzed videos before Run. Unlinked/disconnected cases link to generic Settings. A date window with no qualifying cohort ends in a broad “more comparable ads” state with no exact next action. |

## 4. Correction ledger: still valid, invalidated, newly introduced

| Status | Finding | Why |
|---|---|---|
| **Invalidated by Stage 8.2** | “No Creative Intelligence screen in mounted frontend.” | `main.tsx` mounts `IntelligencePage`; navigation exposes `#intelligence`; it calls the scoped API on explicit submission. |
| **Invalidated by Stage 8.2** | “Creative Intelligence journey stops after account linking.” | A linked Ads account now leads to a real form and result/abstention views. Live result availability remains unverified. |
| **Still valid** | No public landing/product orientation; sparse auth entry. | Stage 8.2 did not change public/auth files. |
| **Still valid** | Settings, integrations and billing are buried; active versus inspected workspace can be ambiguous. | Stage 8.2 did not restructure these surfaces. Pending billing fix addresses one quota path only. |
| **Still valid** | First-time onboarding omits a path to intelligence and uses generic Settings transitions. | Stage 8.2 did not update the five-step onboarding sequence. |
| **Still valid** | No personal account/profile settings destination. | Only email and signout are exposed. |
| **New in Stage 8.2** | New intelligence route adds a sixth primary item and specialist input/result vocabulary. | Account, metric, exact dates, peer cohort, reference ad, evidence coverage and experiments appear in one screen. |
| **New in Stage 8.2** | Result context is incomplete in the UI. | Backend returns `performance.limitations` and top-level `limitations`, but the component renders neither. A “Reference ad value” appears without identifying or explaining how the reference ad was selected; backend chooses the first eligible cohort record. |
| **New in Stage 8.2** | Intelligence setup and recovery point to generic Settings. | No linked Ads account and disconnected-result messages use `#settings`, not the connection/ownership task. |
| **New in Stage 8.2** | On-demand results are ephemeral. | A new run clears prior result; no history, share, export or distinct result URL is present. This is a product decision, not by itself a defect. |

## 5. Critical UX problems and heuristic audit

Severity: **Critical** blocks a core task or could mislead scope/interpretation; **High** materially hinders discovery or completion; **Medium** adds friction/inconsistency; **Low** is polish.

| Principle / severity | User experience and cause | Origin and recommended correction |
|---|---|---|
| First-time orientation — **High** | Signed-out visitor sees a credential form before value, requirements or example outcome. | `AuthGate.tsx`, `AuthPages.tsx`: public product entry and concise auth context. |
| Obvious primary action — **High** | Setup, no-workspace and Home states use different labels for the next step; intelligence is absent from setup. | `OnboardingScreen.tsx`, `CompanyShell.tsx`, `WorkspaceOverview.tsx`: one state-aware next action; separate paths for an idea versus an Ads comparison. |
| Consistent navigation — **Medium** | Six equal sidebar links mix Home, content, intelligence, generation, saved ideas and administration. | `shell/navigation.ts`: group by task and scope; keep existing functionality reachable. |
| Progressive disclosure — **High** | Settings combines plan, OAuth, publishing links, Ads ownership, profile refresh and company lifecycle. | `CompanyManagement.tsx`: split canonical destinations and reveal advanced assignment only when relevant. |
| Visual/information hierarchy — **High** | Intelligence has a page title, a form title, then several long result panels; the first visible result may be below the form. The source and meaning of “Reference ad” are not explained. | `IntelligencePage.tsx`: result summary and context first after Run; explain comparison construction and show key limitations near metrics. |
| Predictable settings placement — **High** | Billing and integrations are scroll targets within Settings; Intelligence recovery links cannot land at the right task. | `CompanyManagement.tsx`, `IntelligencePage.tsx`: explicit workspace Integrations and Billing destinations/deep links. |
| Account versus workspace — **Critical** | Settings can inspect company B while header shows active A; its Billing/ownership refer to B, but profile refresh refers to A. | `CompanyManagement.tsx`, `ProfileRefresh.tsx`: label target scope on each screen and prevent mixed-scope actions in one context. |
| Useful empty states — **High** | Unlinked Ads account points to generic Settings; inadequate historical cohort is explained but gives no specific way to check dates, Ads assignment or analysis readiness. | `IntelligencePage.tsx`: prerequisite-specific recovery and status checklist, without promising source media exists. |
| Useful error recovery — **Medium** | The intelligence form offers a generic retry after broad failures; session/account errors say refresh workspace without a direct control. | `IntelligencePage.tsx`: scoped retry/reload and explanatory next action while retaining safe error text. |
| Mobile usability — **High** | Sticky 112px header, hidden nav/signout, long Settings stack and long intelligence result increase navigation cost. | `shell.css`, `settings.css`, `intelligence.css`: persistent workspace cue, compact mobile navigation and result sections. Existing 390px mock screenshot shows no obvious clipping; that does not prove the whole app is mobile-ready. |
| Accessibility basics — **Medium** | The app has skip link, focus states, labels and native controls. Picker/menu keyboard behavior, dynamic result announcement, heading structure and zoom still need testing. | `AppShell.tsx`, `CompanySelector.tsx`, `IntelligencePage.tsx`: keyboard/assistive-tech review. These are risks, not certified defects. |
| Minimal cognitive load — **High** | “Company,” “workspace,” “AI & Analysis,” “Creative Intelligence,” “Generate,” “Ideas,” “peer,” “reference ad,” and “coverage” require a task/terminology model. | Navigation/onboarding/intelligence copy: shared glossary and progressive explanation, preserving cautious evidence claims. |

**Highest new interpretability risk:** `backend/app/company_intelligence.py` selects a reference record by iterating eligible cohort records. The frontend shows “Reference ad value” and a percentile without identifying that record or exposing returned `limitations`. A user could read the number as account-wide performance. This requires UX/product clarification; this audit does not authorize changing backend selection or response behavior.

## 6. Current information architecture

| Current destination/action | Level | Placement or mismatch |
|---|---|---|
| Public login/signup/reset/legal | Account/public | Root has no product page. |
| Email/signout | Account | Sidebar footer; no account settings. |
| Workspace picker/create/inspect/archive | Workspace | Picker in header; management under Settings; inspection may differ from active workspace. |
| Overview | Workspace | Primary sidebar; “Home” may be clearer. |
| Content/analysis | Feature | Primary sidebar; list-based analysis action. |
| Creative Intelligence | Feature | Primary sidebar; available after Ads-account linking; no deep prerequisite links. |
| Generate and Ideas | Feature | Two primary destinations for create/review of the same saved artifact. |
| Meta authorization | Integration/provider connection | Under Settings and visually interleaved with company management. |
| Publishing/Ads linking and ad assignment | Integration/workspace | “Content ownership” below Billing in Settings. |
| Billing/usage/checkout | Billing/workspace | Generic Settings destination; inspected-company scope. |
| Shared profile refresh | Workspace operation | “AI & Analysis” in Settings, distinct from Creative Intelligence; targets active workspace. |

Navigation is hash-based. Settings section buttons scroll within one page rather than give shareable destinations. Idea details and intelligence results have no direct URL. Onboarding, Content, Intelligence and billing notices repeatedly link to `#settings` for different jobs.

## 7. Proposed information architecture and authenticated shell

**Recommendation for design review:** Four primary workspace destinations: **Home · Creative Intelligence · Content · Ideas**. “Ideas” contains distinct **Create** and **Library** views; this consolidates today’s Generate/Ideas navigation without discarding either behavior. Retain Creative Intelligence as a clearly bounded on-demand comparison, not a promise of universal insight. Workspace switch/create plus **Workspace settings, Integrations, Billing** are grouped under visible workspace context. **Account settings, Help, Sign out** belong to a separate profile control. Do not expose unsupported account-editing features merely to fill that menu.

**Desktop shell:** Product identity, current workspace name/role and switcher in header; four-item feature navigation; utility destinations labeled as workspace-level; personal control separate. Each main page has one title, one purpose line, readiness/status and one primary action. Billing, integrations and archive screens name the target workspace, especially if the user is inspecting one other than the currently selected workspace.

**Mobile shell:** Keep current workspace visible in a compact header. One menu/drawer lists four feature destinations first, then workspace tasks and account tasks in separate groups. Check long workspace names, keyboard/focus return, 200–400% zoom and small landscape view. Avoid forcing a user to scroll a long Settings page to reach Billing or Meta.

**Breadcrumbs:** Use only inside nested destinations such as `Ideas / [idea title]` or a specific integration account. Top-level pages already have workspace context and navigation.

**Direct navigation concept:** A workspace path family such as `/w/:workspaceId/home`, `/intelligence`, `/content`, `/ideas`, `/integrations`, `/billing`, `/settings`, plus `/account`, would make scope explicit. This is a planning example, not a request to rewrite routing now. Before any implementation, specify compatibility for current `#overview`, `#content`, `#intelligence`, `#generate`, `#ideas` and `#settings` links.

## 8. Proposed public entry and auth structure

Provide a public root with a concise outcome, a short process (connect eligible Meta accounts → compare available performance and content evidence → explore observations or make ideas), a clearly labeled example preview, requirements/coverage, Create account and Sign in. A Pricing link needs verified current plan terms; a Help/docs link needs a real destination. Existing legal links remain. Copy must not promise a creative comparison for every linked account or imply observed differences prove cause.

Sign in/signup should explain why an account is needed and what happens after email confirmation. Keep Google and email/password options, reset/callback recovery and clear configuration errors. After auth, go to a validated prior workspace or an explicit choice; first-time setup should ask whether the immediate goal is **make an idea from published content** or **compare Ads performance and creative evidence**, then display only that path's prerequisites. This is a proposed flow; it does not assume new backend capabilities.

## 9. Account-level versus workspace-level ownership map

| Concept | Scope | UX rule |
|---|---|---|
| Auth session, email, Google/password, signout | Person/account | Profile control; no workspace implied. |
| Workspace membership, selected workspace, role | Person's access to workspace | Switcher shows active/available and owner/member where useful. |
| Workspace name, archive/restore, account/ad links | Workspace/company, owner permissions | Always name target workspace; preserve backend role gates. |
| Meta OAuth authorization | Authorized provider connection | Explain that a connection alone does not link a publishing or Ads account to a workspace. |
| Content, analysis, saved ideas and intelligence requests/results | Active workspace | Keep scope visible and clear it on switch; result should state selected account/date/metric. |
| Plan, usage, checkout/portal | Billed workspace | Name the billed workspace and follow backend `can_manage_billing`; never infer Pro from a return URL. |

## 10. Billing/workspace navigation fix: current versus pending

The **clean Stage 8.2 release candidate does not include the fix** found as uncommitted work in the older `v9` checkout. That pending change affects UX and backend billing authorization, so it cannot be silently counted as implemented in this no-code audit.

| Case | Behavior at `b7e085b` | Expected effect of pending main-checkout patch; unverified in RC |
|---|---|---|
| Creation hits `free_workspace_limit_reached` while active workspace is Pro and another owned workspace is Free | Limit notice uses active Pro billing context; upgrade button may not appear, and generic Settings opens inspected active Pro. User cannot easily reach the workspace whose plan must change. | Search owned workspaces' billing data, inspect an eligible Free workspace, scroll to its Billing section, label CTA “View Billing in Settings.” |
| Eligible Free workspace is archived | RC Settings hides its Billing section even if inspected. | Pending UI shows Billing for archived inspected workspace; pending backend changes billing read/checkout/portal authorization to permit archived owned workspace, subject to existing role checks. |
| Multiple eligible Free workspaces or failed billing reads | RC has no target-selection flow. | Pending patch chooses first eligible owned Free workspace from a lookup; does not give an explicit choice or explain lookup failure. |

This fix narrows a real quota dead end but leaves the broader Settings hierarchy, active-versus-inspected ambiguity and billing scope labeling unresolved. It also changes backend authorization for archived billing, so its tests and permission behavior must be reviewed in the separate integration work. No part of it was applied here.

## 11. Screen redesign priority

1. **Scope model and shell/navigation:** clarify active/inspected workspace and canonical destinations. This affects every screen, including the new intelligence view.
2. **Creative Intelligence comprehension and recovery:** explain reference comparison, show material limitations, give account/cohort/media readiness guidance, and define whether results need persistence. Keep causal and evidence boundaries.
3. **First-time Home/onboarding:** offer task-specific paths for an idea or an Ads comparison; make next actions direct.
4. **Integrations and ownership:** make Meta connection, workspace linking and Ads assignment a coherent staged flow.
5. **Billing:** integrate the pending quota navigation fix separately, then give named workspace Billing a direct destination.
6. **Public entry and auth:** establish purpose and expectations before credentials.
7. **Content/analysis:** clarify discovery, queued, analyzed, failed and eligible-source states.
8. **Ideas:** connect Create and Library, then improve detail routing/editor hierarchy.
9. **Workspace/account settings:** place rename/archive/profile refresh and personal controls under correct ownership.
10. **Shared design system and responsive/accessibility pass:** consolidate once information structure is agreed.

## 12. Design-system inventory and inconsistencies

| Area | Stage 8.2 inventory | Candidate shared primitive/rule, without choosing final style |
|---|---|---|
| Typography | System UI with page/section/body tokens; feature CSS also uses raw pixel sizes and legacy eyebrow/caption styles. Intelligence adds compact metric labels and dense evidence text. | Type roles for page, section, result summary, metric, citation, helper and legal/caveat. |
| Colors | Light neutral/teal tokens, semantic status tones; legacy CSS still has literal colors. | Semantic surface/text/action/status tokens and measured contrast. |
| Spacing | 4–64px scale plus fixed legacy values; intelligence uses stacked panels and two-column metric blocks. | Consistent page width, section rhythm, result density and mobile gaps. |
| Buttons/links | Shared Button/IconButton, raw primary buttons, feature CTA links and Settings scroll buttons. | Action hierarchy; link versus button; named task destination. |
| Inputs | Shared native Input/Select/Textarea/Checkbox; raw radio/checkbox in feature forms. Intelligence has account/metric/date grid. | Labeled field, help/error, date range, selection group and filter bar. |
| Cards/panels | Shared Panel, legacy `section` defaults, content/idea cards and intelligence result panels. | Summary, result, list row, document and evidence/citation containers. |
| Navigation/icons | Lucide feature icons, six sidebar items, mobile hamburger, company picker and text signout. | Primary, workspace utility, profile and contextual navigation patterns. |
| Dialogs | Native switch/publication dialogs and external OAuth popup. | Dialog structure, focus return and destructive confirmation. |
| Alerts/empty/loading | Shared Alert/Badge/LoadingState plus raw notice/error patterns. Intelligence adds performance-only/abstention explanations. | Prerequisite empty, recoverable error, partial result, in-progress state. |

No final colors, typeface, motion or visual references are selected by this audit.

## 13. Mobile and responsive issues

The existing CSS collapses intelligence form and metric grids to one column below 600px. I inspected the Stage 8.2 mocked 390px screenshot: its form/result panels fit without obvious clipping, and the validation report records no horizontal overflow in that checked state. The screenshot also shows the long vertical result and a header that spends substantial space on brand, menu and workspace. Account actions and all feature destinations are hidden behind the menu. Settings and older feature views have separate breakpoints and were not freshly verified at this commit. Mobile redesign should prioritize navigation and result scanning, then validate narrow/landscape/zoom/touch behavior with a browser and real content lengths.

## 14. Accessibility issues and strengths

Strengths: document language, skip link, labeled primary nav, `aria-current`, visible focus outline, native form controls and dialogs, loading/status/alert roles, and reduced-motion CSS. Intelligence input labels and disabled-while-running state are present. Check keyboard semantics and focus return for the custom workspace picker/mobile menu, announcement/focus after long intelligence results arrive, heading order when page and panel titles coexist, comprehensibility of raw evidence references, muted-text contrast and zoom. These are audit risks; no fresh assistive-tech certification was performed.

## 15. Recommended redesign phases

1. **Approve the product model:** names, four primary destinations, workspace/account boundaries, intelligence result meaning and first-use goals.
2. **Map flows and routes:** low-fidelity navigation, account/link/analysis/intelligence prerequisites, limit/recovery states, direct links and scope transitions; review against representative tasks.
3. **Design key screens and copy:** intelligence, first-time Home, Integrations, Billing and public/auth, then Content and Ideas; review the evidence/causal caveats with actual result examples.
4. **Define shared components and responsive behavior:** shell, page headings, status/partial results, forms, evidence/citations, dialogs and menus; choose visual direction afterward.
5. **Separately approved implementation and validation:** reconcile the pending billing fix into the release candidate, preserve API contracts, run focused/full checks, desktop/mobile/keyboard review and live provider/media validation where available. No implementation is authorized by this report.

## 16. Backend/API behavior that should not change for this UX redesign

- Keep Supabase auth/session semantics and authenticated FastAPI application requests.
- Keep company membership, role checks, active-workspace validation, archive/restore and scoped cancellation/data isolation. UI labels do not grant access.
- Keep Meta OAuth, connection ownership, publishing-account linking and Ads-account/ad assignment constraints; the UI must distinguish these stages.
- Keep content discovery, analysis eligibility/status, source availability and company-scoped data semantics. Do not imply every linked Ads account provides downloadable source video.
- Keep idea-generation source/target requirements, 1–20 source limit, idempotency, saved lifecycle, feedback and publication-association caveats.
- Keep server-authoritative billing entitlement/usage and hosted checkout/portal verification. The pending archived-workspace billing authorization patch is **not part of this audit** and needs separate integration review; this document does not approve a backend change.
- Keep the Stage 8.2 intelligence request fields, exact-context cohort rules, backend-selected reference ad, bounded evidence/citation contract, structured abstentions, observed-difference and testable-hypothesis caveats. Do not reinterpret small cohorts, partial media coverage or research-only detectors as population accuracy or causal proof.
- No migrations, endpoints, analysis thresholds, model behavior, research contracts or production integrations are proposed here.

## Decisions before visual design

1. Should the product continue to call this destination **Creative Intelligence**, and what concise outcome should it promise given that a run can return performance only or abstain entirely?
2. Should intelligence remain an ephemeral, on-demand report, or does the user need history/share/export? This is a product decision with possible future backend scope; no such work is proposed now.
3. How should the UI explain the automatically chosen reference ad, cohort/peer eligibility and returned limitations without overwhelming the page?
4. Should **Ideas** combine today's Generate and Ideas destinations, as proposed? Should onboarding offer separate idea and Ads-comparison first-use paths?
5. Confirm which workspace owns billing when a Free-workspace limit is hit and how the pending fix should be integrated, especially archived workspaces and multiple eligible Free workspaces.
6. Which public preview, pricing claims and Help destination are supportable today?

## Audit checks and limits

Read the clean Stage 8.2 entry, navigation, auth/session, workspace, onboarding, Overview, Content, Intelligence, Generate, Ideas, Meta, Billing, Settings, shared UI/CSS, legal routes, relevant browser tests and Stage 8.2 validation report. Compared the older checkout's uncommitted billing/workspace frontend and backend diff against the Stage 8.2 worktree. Inspected its existing desktop and 390px mocked intelligence screenshots. Confirmed `git status` clean and HEAD `b7e085b` in the release-candidate worktree. No application code was edited, no runtime tests were rerun for this documentation-only correction, and no live auth, provider, billing, source-media or full mobile flow was exercised. The only changed file for this task is this report in the main checkout.
