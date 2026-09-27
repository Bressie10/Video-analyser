# Video Analyzer V2

Connect Meta → discover business video content → analyze content and collect
performance metrics → select existing videos → **Generate a new video idea**
and script.

The React/TypeScript frontend uses a FastAPI backend and PostgreSQL library.
It supports professional Instagram Reels (and video media discovered by the
library), Facebook Page videos/Reels, and Meta ads with accessible video assets.
TikTok authorization, metrics and manual uploads remain **legacy backend APIs**;
they are not part of the current customer frontend.

After connecting, saved content loads and synchronization discovers new content.
Choose named account filters and select videos. Selecting deferred content prepares
it; ready content reuses saved analysis. One idea can use **1–20 unique ready video
assets**, including assets linked to ads. No customer upload, provider ID, media
URL, or OpenAI key entry is required. Unavailable media and missing metrics remain
visible limitations, not invented data.

- [V3 persistent ideas](backend/PERSISTENT_IDEAS.md): backend API, frozen evidence, lifecycle/feedback and manual publication links.
- [V4 company management](backend/COMPANY_API.md): company lifecycle, account links, explicit ad ownership and frontend API contract.
- [Database and migrations](DATABASE.md): installation, upgrades, schema and metric storage.
- [Backend architecture and APIs](backend/META_LIBRARY.md): synchronization, caching, policies and compatibility routes.
- [Frontend behavior](frontend/LIBRARY_CONTRACT.md): account filters, preparation, selection and results.
- [Development rules](AGENTS.md).

## Local setup on macOS

Install Python with `venv` support, Node.js/npm, FFmpeg (`ffmpeg` and `ffprobe` on
`PATH`), and PostgreSQL with the `psql` client. The supplied Compose service uses
PostgreSQL 17; an existing local PostgreSQL server also works with the configured
`DATABASE_URL`. Docker is needed only for the Compose option. The repository does
not pin Python or Node versions; use versions supported by its dependencies.

From the repository root, create `.env` **only if it does not already exist**:

```sh
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

Edit the private root `.env`, then load it into the shell:

```sh
set -a
source .env
set +a
```

For Compose PostgreSQL:

```sh
docker compose up -d postgres
docker compose exec postgres pg_isready
```

Wait for PostgreSQL to accept connections, then follow the
[ordered migration instructions](DATABASE.md#migrations-and-local-setup).
V2 requires migrations **001–005**; integrated company ownership, profiles and ideas
require **001–010**. Existing installations apply only missing
migrations. The backend does not apply migrations automatically.

Start the backend in a terminal from the repository root:

```sh
set -a
source .env
set +a
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The app also loads root `.env` without overriding existing environment variables.
Explicit shell loading ensures import-time settings such as `WHISPER_MODEL`
are available. Restart with updated environment after configuration changes.

In another terminal:

```sh
cd frontend
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `http://127.0.0.1:8000`.
Backend liveness is `http://127.0.0.1:8000/health`; `/health/db` checks database
connectivity, not migration completeness. FastAPI exposes `/docs` and
`/openapi.json` on the backend origin.

Real Meta OAuth needs the HTTPS setup below. First content processing may download
OCR/Whisper model assets; allow time and network access. Processing uses FFmpeg,
faster-whisper, PySceneDetect, RapidOCR and optical flow. Temporary media is removed
after processing; PostgreSQL retains analysis and performance snapshots.

## Environment configuration

Use [.env.example](.env.example) as the template. Never put server credentials in
`VITE_*` variables or commit `.env`.

| Variable | Purpose / default |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | Local Compose database configuration; keep `DATABASE_URL` consistent |
| `DATABASE_URL` | PostgreSQL connection string; required for V2 |
| `OPENAI_API_KEY` | Backend key for idea generation |
| `OPENAI_MODEL` | Configured model, default `gpt-6-sol`; account availability must be verified separately |
| `META_APP_ID`, `META_APP_SECRET` | Meta app credentials |
| `META_REDIRECT_URI` | Exact HTTPS callback ending in `/api/meta/callback` |
| `META_LOGIN_CONFIG_ID` | Facebook Login for Business configuration ID |
| `META_GRAPH_API_VERSION` | Repository default `v26.0`; not a claim that this is the latest provider version |
| `META_TOKEN_ENCRYPTION_KEY` | Stable Fernet key for persistent Meta authorization; required for V2 |
| `META_WORKER_ENABLED` | Default `true`; `false` disables background workers |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` | Optional legacy TikTok integration; unnecessary for Meta V2 |

`WHISPER_MODEL` is an additional code-supported setting, absent from the template;
it defaults to `base`. Test-only variables are described below.

Generate a Fernet key locally after installing backend dependencies:

```sh
backend/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Put the generated value in your private `META_TOKEN_ENCRYPTION_KEY` setting and
keep it stable across restarts. Replacing it requires reconnecting Meta. User
access tokens are encrypted in PostgreSQL; browser session tokens are stored as
hashes. OAuth state is still short-lived process memory. Expired/revoked access
requires reconnecting; persistence does not make tokens permanent.

Without an encryption key, the compatibility OAuth session can connect in memory,
but library endpoints return 503. This is not a working V2 configuration.

## Meta development setup

1. Create an app in the [Meta app dashboard](https://developers.facebook.com/apps/)
   with the business use cases needed for Facebook Login for Business, Instagram
   and Marketing API reads. Dashboard options depend on the app configuration.
2. Enable [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/).
   Create a configuration with **User access token**, select the required asset
   access and permissions below, and copy its ID to `META_LOGIN_CONFIG_ID`.
3. Set the app ID/secret, Graph version and exact HTTPS callback in `.env`.
   Register that same callback as a **Valid OAuth Redirect URI** in Meta's login
   settings. The backend authorizes with `config_id`, not a separate scope override.
4. During development with Standard Access, use a user with a role on the Meta
   app (admin/developer/tester) and access to the intended Pages/ad accounts.
   Instagram requires a professional account linked to an accessible Page.
   Serving users without app roles requires the relevant Advanced Access/App Review.
5. Restart the backend, open the app at its HTTPS origin and select **Connect Meta**.
   Complete the popup authorization. The callback saves authorization and returns
   a sync job; the frontend reads the library and polls progress.

The backend requires all of these granted business permissions:

| Permission | Use |
| --- | --- |
| `pages_show_list` | Discover accessible Pages |
| `pages_read_engagement` | Read Page content and support insights access |
| `pages_read_user_content` | Required by the backend's Instagram/Page permission set |
| `read_insights` | Facebook video/Reel insights |
| `instagram_basic` | Linked professional Instagram accounts/media |
| `instagram_manage_insights` | Instagram insights |
| `ads_read` | Authorized ad accounts and ad insights |

The permission allowlist also accepts optional `pages_manage_engagement`, plus
Meta's `public_profile` and `email` grants; the app does not read email or perform
Page writes. Missing or unexpected business permissions are rejected. Facebook
insights access can depend on Page tasks and provider requirements; validate actual
asset access rather than treating a successful login as proof of all permissions.
Consult Meta's [permissions reference](https://developers.facebook.com/docs/permissions/)
and [access levels](https://developers.facebook.com/docs/graph-api/overview/access-levels/).

### HTTPS tunnel for OAuth

An HTTPS tunnel is optional for local UI work and fixture tests, but needed for
real OAuth when you do not already have a public HTTPS development origin.
Expose Vite so the frontend and proxied `/api` share the same origin. For example,
with `cloudflared` installed:

```sh
cloudflared tunnel --url http://localhost:5173
```

For the hostname printed by the tunnel:

- Set `META_REDIRECT_URI=https://YOUR_TUNNEL_HOST/api/meta/callback`.
- Set the identical **Meta Valid OAuth Redirect URI**.
- Replace the temporary entry in `frontend/vite.config.ts` `server.allowedHosts`
  with `YOUR_TUNNEL_HOST` (hostname only), then restart Vite.
- Reload the backend environment/restart it and open the HTTPS frontend URL.

[Cloudflare quick tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
use a temporary random hostname. After a tunnel restart, update **all three**
settings above. Do not preserve a particular temporary hostname in shared docs.
Secure session cookies require the same HTTPS origin for real browser OAuth.

## Testing

Run commands from the indicated package. There is no configured frontend lint
script or backend lint configuration; do not substitute a nonexistent lint command.

Backend unit/API tests, from `backend`:

```sh
.venv/bin/python -m unittest discover -s tests
```

These include mocked Meta/TikTok/OpenAI calls. PostgreSQL tests are skipped unless
`TEST_DATABASE_URL` points to a disposable database; they create/drop isolated
schemas and cover migrations, repositories, ownership, caching, jobs and APIs:

```sh
TEST_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/TEST_DB' .venv/bin/python -m unittest discover -s tests
```

Add `RUN_MEDIA_INTEGRATION=1` for generated-sample media tests using FFmpeg and
local OCR/Whisper models. `HF_HUB_OFFLINE=1` prevents Hugging Face downloads when
the required Whisper model is already cached; it is not a model installation step.
The rollback-only SQL schema check is documented in [DATABASE.md](DATABASE.md).

Frontend checks, from `frontend`:

```sh
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser tests use mocked application responses and cover connection, filters,
pagination, deferred preparation, selection limits, results, failures and desktop/
320px layouts. They do not establish live provider access.

For browser → Vite → real FastAPI → worker/media analysis → PostgreSQL → UI:

```sh
TEST_DATABASE_URL='postgresql://USER:PASSWORD@localhost:5432/TEST_DB' npm run test:integration
```

This requires a PostgreSQL role with **CREATE DATABASE** permission, backend
`.venv` dependencies, FFmpeg, cached OCR/Whisper models and Playwright Chromium.
The harness creates/drops its own database and starts its own servers. It uses
real routes, sessions, jobs, analysis, persistence and recommendation evidence
assembly; external Meta, media delivery and OpenAI are controlled fixtures.

Live verification remains separate: complete real OAuth, confirm access to each
intended source and downloadable media/insights, and generate with an authorized
OpenAI key. Automated fixtures do not prove provider permissions, model access,
or output quality on real business footage.

## V3 company profile subsystem

See [Company profiles](COMPANY_PROFILES.md) for the integrated 006 ownership adapter,
migration 007, asynchronous refresh APIs, scoped evidence, invalidation hooks and tests.
The real adapter is bound by default; apply both migrations before company operations.
The background worker remains opt-in via `COMPANY_PROFILE_WORKER_ENABLED=true`.
Existing Meta sessions must reconnect once to receive the `/api` cookie used by company routes.

## V4 Wave 1 company integration

The app uses one global company selection, persisted as an internal UUID and
validated against accessible active companies at startup. Create requires only a
name; account setup is optional. Manage companies supports rename/archive/restore,
manual Facebook/Instagram/Ads-account linking, and individual ad assignment,
unassignment and reassignment. Meta connects once for the existing session.

Wave 2 now mounts company-scoped content browsing, generation and saved ideas.
Legacy global media preview, preparation and sync controls remain unavailable in
the active-company workspace until scoped capabilities exist. The selector never
labels all-company library data as belonging to the selected company. See
[company state](frontend/COMPANY_STATE.md), [UI contract](frontend/COMPANY_UI_CONTRACT.md),
and [API contract](backend/COMPANY_API.md).

From `frontend`, run `npm run test:company`, `npm run test:companies`, and
`TEST_DATABASE_URL=postgresql://USER@localhost:PORT/DISPOSABLE_DB npm run test:company-integration`.
Use a disposable UTF-8 PostgreSQL database; the integration fixture creates and
drops its own schema. Company routes, session authorization, and ownership are real;
Meta status is a controlled external-provider fixture. No live OAuth or provider
access is established by these tests.

### V4 company content browsing (Wave 2)

`GET /api/companies/{company_id}/content` uses the existing Meta session cookie
and returns `Cache-Control: private, no-store`. Missing/expired/disconnected
sessions return 401; unknown, foreign-connection and archived companies return
404. Invalid query values return 422; storage failures return the existing
sanitized 503 response. No discovery, analysis, jobs or selection writes occur.

| Query | Contract |
| --- | --- |
| `analyzed_only` | Boolean, default `false`. `true` selects video/reel items with completed current-version analysis and a matching stored video/version in the authenticated connection. |
| `platform` | Optional `facebook`, `instagram`, or `meta_ads` (friendly provider keys, not provider IDs). |
| `content_type` | Optional `video`, `reel`, or `ad`. |
| `search` | Optional 1–200 characters; trimmed, case-insensitive literal substring of the safe `display_title`. SQL wildcard characters have no special meaning. Whitespace-only search behaves like no search. |
| `published_from`, `published_to` | Optional inclusive ISO-8601 timestamps with timezone; from must not exceed to. Undated items do not match a supplied date bound. |
| `limit` | Integer 1–100, default 20. This browsing page size does not change the persistent-idea source limit of 1–20. |
| `offset` | Nonnegative integer, default 0. Use `next_offset` with the same filters/order for subsequent pages. |
| `sort` | Only `published_at`, the default. |
| `order` | `desc` (default) or `asc`. |

Response shape (all item fields are always present):

```json
{
  "items": [{
    "library_item_id": "internal-library-item-uuid",
    "video_id": "internal-video-uuid-or-null",
    "platform": "facebook",
    "content_type": "video",
    "published_at": "2026-01-01T00:00:00+00:00",
    "analysis_state": "completed",
    "analyzed": true,
    "display_title": "Facebook video",
    "summary": {"duration_seconds": 5.0, "width": 1920, "height": 1080}
  }],
  "next_offset": null
}
```

`video_id` and `published_at` are nullable. Summary numbers are nullable when
unavailable. `analysis_state` is the existing stored pipeline state; `analyzed`
is derived readiness, so a completed item with obsolete/missing analysis is
not ready. Ad rows are not analyzed video sources; their accessible creative
video rows appear separately. There is no new stored readiness flag.

Company ownership is applied in SQL **before** filters, ordering and pagination,
using V3's real ownership repository. Organic accounts are exclusive to their
owner. Linking a shared Ads account grants no content: only explicitly assigned
ads and their content-only creative assets are accessible. A creative reference
never grants access to sibling ads, labels or metrics, including when the
creative is also an organic item. Foreign-connection assets and video analysis
are excluded. Company/session locks fence ownership changes through the read.

Ordering is publish timestamp followed by internal library-item UUID, both in
the requested direction; null timestamps always come last. Unknown dates are
not replaced by discovery dates. `next_offset` is null at the end. Ordering is
deterministic for unchanged data; offset pages are not a multi-request snapshot,
so refresh from offset 0 after ownership/content changes.

For frontend **All analyzed content**, request
`?analyzed_only=true&limit=20&sort=published_at&order=desc` without other filters
and use only that first page. It returns up to 20, including fewer or zero when
appropriate. For manual selection, browse subsequent analyzed pages as needed
and select 1–20 `library_item_id` values. Existing persistent-idea APIs call this
source-ID list `video_ids`; do not substitute the analysis `video_id`.

Cards deliberately exclude performance, raw provider identifiers, provider media
URLs, tokens and raw errors. Organic/creative labels have no safe provenance in
V2 storage, so their titles are generic. Assigned ads use the existing management
API's friendly-label rules (fallback for blank labels, provider-ID labels and
URLs). Search cannot match suppressed labels. There is no safe thumbnail/media
proxy in this contract, and no thumbnail URL is returned. Frontend should render
plain text and a placeholder image, clear selections on company change, and use
`analyzed` to determine source eligibility. The integrated frontend follows these rules.
## V4 Wave 2 idea API

The company-scoped persistent generation and history API is documented in
[the idea API contract](backend/IDEA_API.md), including explicit source/target
selection, filters, cursor pagination, Save, feedback and publication associations.
The integrated frontend enables generation, history, explicit editing, feedback,
lifecycle and publication links without adding a migration. See
[V4 Wave 2 integration and verification](V4_WAVE2_INTEGRATION.md).
