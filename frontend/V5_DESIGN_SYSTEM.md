# ContentMetric V5 shared design contract

Agent A owns the foundation. Feature agents should import it, scope new CSS to their feature, and avoid editing shared files concurrently. Feature page content remains V4; the Overview entry links are intentionally minimal.

## Shared files and boundaries

- `src/styles/tokens.css`: authoritative semantic tokens; `base.css`: native element defaults and V4 compatibility; `primitives.css`: shared component styling.
- `src/ui/controls.tsx`: Button, IconButton, Input, Textarea, Select, Checkbox.
- `src/ui/layout.tsx`: Badge, Panel, PageHeader, SectionHeader, EmptyState, Divider, Alert, Skeleton, LoadingState, PageLayout, TableContainer.
- `src/shell/AppShell.tsx`, `shell.css`, `navigation.ts`: shared header, navigation, layout and hash navigation.
- `src/main.tsx`, `CompanyShell.tsx`, `CompanySelector.tsx`, `style.css`: shared integration; coordinate changes through the foundation owner.
- Feature agents own their feature components/styles. The Overview agent can replace `src/shell/WorkspaceOverview.tsx`. Coordinate any relocation/import change in `main.tsx`.
- Keep company store/provider, switch guards, backend contracts and `vercel.json` unchanged for presentation work.

## Palette

Use `var(--color-…)`, never introduce feature-specific accent palettes. Light mode is the only current theme; semantic tokens permit a later theme override. V4 aliases (`--ink`, `--muted`, `--surface`, `--line`, `--accent`, `--soft-accent`) remain supported.

| Token suffix | Value | Use |
| --- | --- | --- |
| app | #f6f7f9 | App canvas |
| surface / elevated | #ffffff | Panels / dropdowns and dialogs |
| subtle | #eef1f3 | Quiet grouping, skeletons |
| text | #202932 | Primary content |
| text-secondary / text-muted | #52616c / #64727d | Supporting text / captions |
| border / border-strong | #dce2e6 / #b6c2ca | Surfaces / controls |
| accent / accent-hover | #17665e / #104f49 | Primary actions, links, focus |
| hover / active | #edf2f2 / #e5f1ee | Hover / selected navigation |
| success / success-subtle | #25623f / #eaf4ed | Success text / background |
| warning / warning-subtle | #805711 / #fff5df | Actionable caution |
| danger / danger-subtle | #a12c32 / #fcedee | Errors, destructive actions |
| info / info-subtle | #285c8c / #ecf3fa | Informational notices |
| on-accent / backdrop | #ffffff / #20293266 | Primary button text / modal overlay |

## Type, spacing and geometry

System UI font stack; no external font downloads. Root 16px, body `--text-body` 15px/1.6. Page titles `--text-page` 30px/1.2, weight 650; mobile 26px. Section titles 20px/1.35, card titles 16px/1.4, weight 650. Secondary text, labels, navigation and buttons 14px; captions 12px. Do not use captions for primary content. One visible h1 (the shell's PageHeader); feature sections start at h2.

Spacing tokens `--space-{1,2,3,4,5,6,8,10,12,16}` map to 4, 8, 12, 16, 20, 24, 32, 40, 48, 64px. Prefer 24–32px between sections, 12–16px between related controls, 8px between icon and text.

Radii: `--radius-control` 6px, `--radius-card` 8px, `--radius-surface` 10px. Small badges use 4px. No routine pill shapes. One-pixel borders; stronger border for inputs. No card shadows; `--shadow-popover` only for floating menus/dialogs. No gradients, decorative animation or glass panels.

## Components and states

- `Button variant="primary|secondary|ghost|danger"`: secondary default; explicit primary for the principal action. Ghost for low-priority utilities, danger only for destructive actions. Defaults to `type="button"`; use `type="submit"` intentionally. Disabled buttons are visibly muted; focus-visible uses a 3px teal outline with 3px offset.
- `IconButton label="…"`: required accessible action label; 44×44px. Decorative Lucide icons use `aria-hidden`.
- Native Input, Textarea, Select wrappers forward HTML props/ref. Associate every input with a label; use `aria-describedby` for help/errors and `aria-invalid` for invalid fields. Inputs have at least 44px height. Checkbox requires a `label`; radio groups use fieldset/legend. Keep native keyboard interaction.
- `Panel` is an optional bordered surface, not a mandatory wrapper. Use open layouts, separators and spacing first. Do not nest panels. V4's broad section styling is compatibility only; feature-owned semantic sections should reset that framing with scoped CSS or use PageLayout/div wrappers.
- `Badge tone="neutral|success|warning|danger|info"`: concise status text; colour is supplemental, never the only signal. Do not announce static badges as live status.
- `PageHeader` is already rendered by the shell. Use SectionHeader within feature content; `actions` accepts a small group of controls. Panel headings use h3 if subordinate to h2.
- `EmptyState`: specific title, brief explanation, optional decorative icon and useful action. `LoadingState` has a live status label; Skeleton is decorative and static (no shimmer). Error notices use `Alert tone="danger"`, safe copy and a retry where meaningful; informational notices use `tone="info"`. Do not expose raw provider errors.
- Company dropdown uses a disclosure button, `aria-expanded`, `aria-controls`, ordinary buttons and Tab order; Escape returns focus to its trigger; outside interaction closes it. Reuse its border, surface, radius and shadow rules for other disclosures. Do not claim ARIA menu semantics without implementing menu keyboard behavior.
- Use native `<dialog>` with a labelled title, `showModal()`, initial focus, Escape handling and focus restoration. Existing company confirmation and publication dialogs remain in place. Do not implement a second modal framework.
- `TableContainer label="…"` provides a labelled, focusable horizontal scroll region. Use semantic table headers; mobile scrolling belongs inside the container, never on the document. Lists should wrap long content and maintain `min-width: 0`.
- No tooltip abstraction: prefer visible labels. Add accessible tooltip behavior only when a real use case needs it.

Example:

```tsx
import { Button, Input } from '../ui/controls';
import { PageLayout, SectionHeader, Panel, Badge } from '../ui/layout';

<PageLayout width="form">
  <SectionHeader title="Details" />
  <Panel>
    <label htmlFor="title">Title</label>
    <Input id="title" value={title} onChange={e => setTitle(e.target.value)} />
    <Badge tone="success">Saved</Badge>
    <Button variant="primary" onClick={save}>Save changes</Button>
  </Panel>
</PageLayout>
```

## Shell, layout and navigation

Desktop: 72px sticky header, 216px persistent sidebar, 32px content gutters. At 701–1100px: 184px sidebar, 24px gutters, labels stay visible. Main fills available width up to `--page-width` 1600px. PageLayout defaults wide; reading and form variants cap at 800px and 640px and remain left aligned. Do not reintroduce a narrow universal column.

At ≤700px: compact 112px two-row header, full-width company control, labelled navigation disclosure. The menu opens in document flow, without overlay or focus trap. Opening focuses the current link, Escape restores the menu button, destination selection closes it and focuses main. Content gutters 16px; controls at least 44px. Keep layouts usable at 320px, with long company names and zoomed text.

Navigation: `/#overview` (also `/`), `/#content`, `/#generate`, `/#ideas`, `/#settings`. Native hash anchors support refresh/back/forward without a routing dependency or Vercel changes. Unknown hashes fall back to Overview. `navigation.ts` owns labels, icons and descriptions. Settings has a divider separating it from primary workflows.

Company selector remains global. It calls the existing CompanyShell guarded switch and CompanyStore; store only the internal UUID, clear inaccessible/archived/invalid selections, never choose a fallback silently. No-company state keeps shell navigation and management usable. Settings hosts the existing company administration and Meta connection UI. Connection component stays mounted to preserve its status/OAuth effects.

Content, Generate and Ideas stay mounted behind native `hidden` wrappers so navigation preserves their existing local state and registered company-switch guards. Company changes still reset through existing company boundaries. Preserve this lifetime model unless explicitly redesigning and testing draft/guard semantics. Brief typing alone did not register a V4 company guard; generation-in-progress and idea edits retain their existing guards.

Legal pages `/privacy`, `/terms`, `/data-deletion` resolve before any company provider or shell is mounted. They retain standalone layouts and original content. `/api/:path*` proxy remains first and points to the unchanged Render backend.

## Accessibility and verification

Use links for navigation, buttons for actions, semantic landmarks, one visible page h1, readable labels, and visible focus. Respect `hidden`; its `!important` rule prevents legacy display rules from exposing inactive pages. Other `!important` usage is confined to reduced-motion accessibility. Always pair status colour with text. Use named imports from `lucide-react`, normally 20px navigation icons at stroke 1.75; no emoji navigation or hand-built icon set.

Run `npm run typecheck`, `npm run build`, `git diff --check`. `npm test` runs every suite sequentially, including real FastAPI/PostgreSQL fixtures; set TEST_DATABASE_URL to a disposable database and provide backend/.venv. There is no configured lint script. `npm run test:foundation` runs focused shell tests. Optional V5_SCREENSHOT_DIR outside the checkout saves review screenshots. Check all five destinations at 1440, 1280, 1024, 768, 390 and 320px, keyboard focus, dropdowns and public legal routes. Local mocks and offline model fixtures do not prove live Meta/OpenAI or deployment.
