# Video Analyzer

Minimal local development scaffold for a React frontend and FastAPI backend.
See [DATABASE.md](DATABASE.md) for the PostgreSQL table and column reference,
example rows, and setup commands.

Video processing requires `ffmpeg` and `ffprobe` to be installed and available
on your shell `PATH`.

## Run locally

PostgreSQL (with Docker Compose):

```sh
cp .env.example .env
docker compose up -d postgres
```

The local PostgreSQL credentials and port are configured in `.env`. If you
change them, update `DATABASE_URL` there too. Apply the schema once after the
database is ready:

```sh
set -a
source .env
set +a
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/001_create_video_analysis.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/002_create_tiktok_video_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/003_platform_agnostic_performance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/migrations/004_meta_ads_metrics.sql
```

To check that the schema can round-trip representative processing output,
run `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/tests/schema_roundtrip.sql`.
The check rolls back its sample rows.

When `DATABASE_URL` is set, successful uploads store metadata, transcript
segments, scenes, on-screen text (which may include popup text), and motion events. The
response includes `video_id`. Without a configured database, uploads still
return analysis but do not provide an ID for later recommendations. Keep
`.env` private.

Frontend:

```sh
cd frontend
npm run dev
```

Backend:

```sh
cd backend
source .venv/bin/activate
set -a
source ../.env
set +a
uvicorn app.main:app --reload
```

Install backend requirements into `.venv` first if needed with
`python -m pip install -r requirements.txt`. `GET /health` checks API liveness;
`GET /health/db` checks the configured PostgreSQL connection by running
`SELECT 1`. It returns HTTP 503 when `DATABASE_URL` is missing or PostgreSQL
is unavailable.

The frontend entry point is `frontend/src/main.tsx`. The API entry point is
`backend/app/main.py`; `GET /health` returns a liveness response.

The frontend now starts with **Connect Meta → choose business accounts → sync
content → select videos → Generate a new video idea**. It displays a combined
concept and script, supports selection across multiple pages of content, and
requires no file upload, media URL, account ID entry, or customer API key.

**Integration status:** Meta authentication and account discovery use existing
backend routes. Library sync, saved readiness, and multi-video generation use a
**proposed frontend contract**. Concurrent backend library work in this checkout
uses different routes and response shapes; it has not been integrated with or
validated against this frontend. Until the contract is aligned, missing or
incompatible responses produce a friendly unavailable/update-error state.
It never supplies demo videos in production. See
[the library contract](frontend/LIBRARY_CONTRACT.md) for the exact integration
boundary and expected server behavior. Generation assumes server-configured
credentials. The former TikTok/manual-upload frontend is removed; existing
backend upload, analysis, metrics, and single-video recommendation routes remain.

From `frontend`, run `npm run typecheck`, `npm run build`, and
`npm run test:e2e`. Browser tests intercept requests using the proposed contract;
they prove frontend behavior, not live Meta imports, persistence, or generation.
There is no frontend lint script configured.

For programmatic uploads, videos remain capped at 500 MiB and 10 minutes,
normalised to MP4/H.264/AAC (maximum 1,920 pixels per dimension), then have mono
16 kHz PCM WAV audio extracted during the request. Processed files are temporary
and are not retained yet.

Successful video uploads include a `metadata` hash map containing the source
duration, container, file size, overall bitrate, and nested video/audio stream
details such as FPS, resolution, codecs, frame count, sample rate, and channels.
The first upload also downloads and loads the `base` faster-whisper model, then
returns full transcript text and timestamped segments under `audio`.
It also uses PySceneDetect content detection to return scene boundaries and cut
timestamps under `scenes`.
Sampled frames are analysed by RapidOCR; `on_screen_text` lists recognized text,
quadrilateral bounding boxes, confidence, and appearance/disappearance timestamps.
Dense optical flow also returns timestamped `motion_events`, distinguishing
whole-frame pan/zoom/shake patterns from local and general movement.

## Model access

Set `OPENAI_API_KEY` in your private `.env` for a backend default key; the
backend loads it at startup. `OPENAI_MODEL` defaults to `gpt-6-sol`. With
PostgreSQL configured, `GET /api/videos/{video_id}/analysis` returns the saved
result and `POST /api/videos/{video_id}/recommendations` sends it to the OpenAI
Responses API. A caller can supply `X-OpenAI-API-Key` on that POST request to
use their own key for that request. The header takes precedence over the
backend default and is never stored. The response contains only `model` and
plain text `response`. No output schema is defined yet.
The model instructions compare all supplied videos, cite evidence for patterns,
state uncertainty, and generate an original idea and script. The current
recommendation route supplies one stored video, so it cannot yet compare across
videos. It can use performance metrics when they were fetched with the upload.
Send runtime keys over HTTPS and exclude this header from proxy request logs.

## TikTok connection

Add `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REDIRECT_URI` to the
private `.env`. Register the redirect URI in TikTok Login Kit as an HTTPS URL
ending in `/api/tiktok/callback`, and obtain approval for Login Kit and Display
API `video.list` access. Open `GET /api/tiktok/connect` in a browser to authorize;
TikTok returns to the callback, which sets an HTTP-only session cookie. Then
call `GET /api/tiktok/videos` to receive one page of public videos with the
available view, like, comment, and share counts. Pass `cursor` to fetch the next
page when `has_more` is true. Only `video.list` is requested. TikTok requires
the public client key in the authorization redirect; the client secret and
user tokens stay on the backend.

Tokens are kept in backend process memory and refreshed when needed. A backend
restart or a different worker requires the user to authorize again. When
uploading a video, optionally provide its full TikTok video URL after connecting
the account. The backend uses TikTok's video query API to fetch available view,
like, comment, and share counts, then saves them with the processed video under
the same internal UUID. The URL and TikTok video ID are used only for the lookup;
they are not stored. Only canonical HTTPS video URLs are accepted, and the
authorized TikTok account must own the public video. The uploaded file is not
automatically matched against TikTok's video content.
For a real OAuth flow, serve the frontend and `/api` under the same HTTPS origin
so the secure session cookie reaches the upload request.

## Common performance metrics

Analysis responses keep counts in `performance_metrics` (view_count, like_count,
comment_count, share_count) and provenance separately in `performance_source`.
Supported source identifiers are `tiktok`, `instagram`, `facebook`, and `meta_ads`;
TikTok uploads, Instagram Reel attachment, and Facebook video/Reel attachment are implemented. Missing
counts are null, never assumed zero.
Uploads without performance data omit both fields. Each analyzed video still has
one count snapshot. Source IDs and URLs are not persisted.

Apply migrations 003 and 004 before running the updated backend, including on
existing databases. They preserve existing snapshots and retrieval timestamps.
Migration 004 adds optional ad metrics; non-ad response shapes stay unchanged.

To run backend checks, use `cd backend && .venv/bin/python -m unittest discover -s tests`.
Set `TEST_DATABASE_URL` to a disposable PostgreSQL database to include the
migration/repository/API test; it creates and removes an isolated test schema.
Without that variable, the database integration test is skipped.

## Meta authentication (backend only)

Meta login uses **Facebook Login for Business**, with a **User access token**
configuration. Login checks authorization and reads only the authorized user's
app-scoped ID to verify identity; only the connection status is returned to the browser. The separate Reel endpoint below fetches Instagram metrics on
request; login itself does not collect metrics.

Set these variables privately in the root `.env` (never `VITE_*` variables):

| Variable | Value |
| --- | --- |
| `META_APP_ID` | Your Meta business app ID |
| `META_APP_SECRET` | Your app secret |
| `META_REDIRECT_URI` | Exact HTTPS URL ending in `/api/meta/callback` |
| `META_LOGIN_CONFIG_ID` | Facebook Login for Business configuration ID |
| `META_GRAPH_API_VERSION` | `v26.0` (current version verified 2026-09-26) |

In the Meta app dashboard, enable Facebook Login for Business and the relevant
Instagram/Marketing API use cases. Register `META_REDIRECT_URI` as a Valid OAuth
Redirect URI. Create a login configuration with **User access token** as the
token type, selecting these required business permissions:

| Permission | Purpose for the planned read-only integration |
| --- | --- |
| `pages_show_list` | Discover Pages the authorizing user manages |
| `pages_read_engagement` | Read Page-owned organic content; dependency of insights |
| `pages_read_user_content` | Listed dependency of `instagram_basic` in Meta's current permission reference |
| `instagram_basic` | Read linked professional Instagram profile/media |
| `read_insights` | Facebook video/Reel insights |
| `instagram_manage_insights` | Linked Instagram Reel insights |
| `ads_read` | Read ad-level Meta Ads insights for authorized ad accounts |

The URL uses `config_id`, rather than a separate scope override, as Meta
recommends. Configure the list above in the dashboard; `public_profile`
and `email` may be automatically granted by Meta. The backend verifies
`/me/permissions`, rejects missing or unexpected business permissions, and
never requests email data. Optionally allow `pages_manage_engagement` for Facebook
video insights as described below; no Page engagement writes are implemented.
No publishing, ads management, messaging, or
Business Manager management permission is requested. A linked Facebook Page
and a Business/Creator Instagram account are assumed for future Instagram
access; consumer Instagram accounts are outside this login route.

For development, authorize with an app-role user who has access to the intended
assets. Serving other businesses requires the appropriate Advanced Access/App
Review. Authentication and a successful identity check alone do not demonstrate
all requested permissions for App Review.

### Connect and prove the authenticated request

1. Restart the backend with the environment configured. Use one backend worker
   and expose `/api/meta` at the registered HTTPS origin.
2. In a browser, open `https://YOUR_HOST/api/meta/connect` and complete Meta's
   login and consent.
3. The callback exchanges the code server-side, verifies the granted permissions,
   and calls `GET https://graph.facebook.com/v26.0/me?fields=id`. Success returns
   `{"connected": true}` and sets an opaque session cookie.
4. In that same browser, visit `https://YOUR_HOST/api/meta/test`. It repeats the
   authenticated identity request and returns the same safe response.

The test proves a user token can make a Graph request, not that every selected
Page/ad account or future metrics endpoint is accessible. Asset-specific access
will need checking when those integrations are implemented.

Tokens and OAuth state stay in process memory. Cookies are Secure, HttpOnly,
and SameSite=Lax and contain only opaque identifiers. State expires after ten
minutes and can be consumed once. Sessions expire with the returned user token;
expiration, revocation, backend restart, or another worker requires reconnecting.
Long-lived token exchange and persistent/shared token storage are not included.

The client fixes the Graph host, rejects arbitrary URLs and redirects, uses a
Bearer header and `appsecret_proof` for authenticated reads, and exposes only
allowlisted identity fields. Provider error payloads are not returned or logged.
The documented token exchange uses GET; the backend redacts Graph query strings
from HTTPX logs and OAuth callback query strings from Uvicorn access logs.
Configure any external proxy/APM to omit callback query strings, outbound token
exchange URLs, authorization headers, and response bodies too.

Run `cd backend && .venv/bin/python -m unittest discover -s tests -p test_meta_api.py`
for the mocked OAuth/client checks. A real successful callback and `/api/meta/test`
are required for live verification; passing mocked tests does not establish this.

References checked against Meta's documentation on 2026-09-26:

- [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business/)
- [Manual code exchange and permission checks](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/)
- [Permissions and their dependencies](https://developers.facebook.com/docs/permissions/)
- [Instagram with Facebook Login setup](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/get-started)
- [Securing Graph requests](https://developers.facebook.com/docs/graph-api/securing-requests/)
- [Graph API version changelog](https://developers.facebook.com/docs/graph-api/changelog/)

## Attach Instagram Reel metrics to an analyzed video

After Meta authorization, send a JSON request on the same HTTPS origin:

```http
POST /api/meta/instagram/reels/17895695668004550/metrics
Content-Type: application/json

{"video_id": "YOUR_INTERNAL_VIDEO_UUID"}
```

Use the existing `meta_session` cookie from login. The numeric path value is an
**Instagram Graph media ID**, not the shortcode in a public Reel URL or a Facebook
video ID. Obtain it from Meta's tools or the authorized Instagram account's
`/{instagram-account-id}/media` listing. The UUID must be the `video_id` returned
by an earlier upload. The caller selects the matching video; the backend does
not compare uploaded content with Instagram or resolve public Reel URLs.

The backend reuses `MetaClient` and its Facebook User access token:

1. Read `/{instagram-media-id}?fields=id,media_type,media_product_type` and verify
   the ID and `VIDEO` / `REELS` classification.
2. Read `/{instagram-media-id}/insights?metric=views,likes,comments,shares`.
   Media insights default to a single lifetime value per metric.
3. Save the common snapshot to `video_performance` using the supplied internal
   UUID, then return:

```json
{
  "video_id": "YOUR_INTERNAL_VIDEO_UUID",
  "performance_source": "instagram",
  "performance_metrics": {
    "view_count": 120,
    "like_count": 12,
    "comment_count": 0,
    "share_count": null
  }
}
```

| Instagram insight | Common metric |
| --- | --- |
| `views` | `view_count` |
| `likes` | `like_count` |
| `comments` | `comment_count` |
| `shares` | `share_count` |

Only the requested Instagram insights are used. No deprecated play-count
fallback, ad totals, crossposted Facebook counts, reach, or inferred values are
substituted. Missing metrics, empty values, and null values remain null; an
explicit zero remains zero. Meta documents that insight data may be delayed.

A successful refresh replaces the previous Instagram snapshot, including
replacing newly unavailable counts with null, and updates `fetched_at`.
`GET /api/videos/{video_id}/analysis` reads the saved snapshot as before.
The existing schema stores one snapshot per video and does not retain the
external media ID. Use the same Reel ID when refreshing a video's snapshot.
Requests cannot overwrite a snapshot from another platform (409).

Unknown internal UUIDs return 404; non-Reels or completely unavailable counts
return 422 without changing stored data. The existing contract requires at
least one known count. Malformed responses and provider errors return 502;
expired/revoked authorization returns 401. Database failures return 503.
Instagram adds no schema changes; apply all migrations for the current backend.

This requires the authorized professional Instagram account and its connected
Page, plus `instagram_basic`, `instagram_manage_insights`, and
`pages_read_engagement` (already in the login configuration). Meta also documents
additional ads permissions for some Business Manager-assigned Page roles; this
implementation does not broaden OAuth permissions or bypass access failures.
Use an account with the required Page/media access. No Facebook or ads metrics
endpoint is called.

References verified on 2026-09-26:
[Instagram media fields](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/),
[media insights, metrics, permissions, and response format](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/insights/),
and [insights access requirements](https://developers.facebook.com/docs/instagram-platform/insights/).
Requests use the existing configured Graph API version.

The backend suite includes mocked Graph responses plus a real PostgreSQL
API-to-repository round trip when `TEST_DATABASE_URL` is set. Live Reel access
still requires configured Meta credentials, browser authorization, and an
accessible Reel; mocked Graph tests do not establish live provider access.

## Attach Facebook video or Reel metrics to an analyzed video

Using the existing Meta session on the same HTTPS origin, send either:

```http
POST /api/meta/facebook/videos/FACEBOOK_VIDEO_ID/metrics
POST /api/meta/facebook/reels/FACEBOOK_VIDEO_ID/metrics
Content-Type: application/json

{"video_id":"INTERNAL_VIDEO_UUID","page_id":"FACEBOOK_PAGE_ID"}
```

Use numeric Graph video and Page IDs, not public URLs, Instagram media IDs or
Page post IDs. Select `videos` for a regular video and `reels` for a Reel. The
caller supplies the media kind and the association with the uploaded analysis;
this endpoint does not identify matching content or infer Reel status from
video duration. Crossposted videos have different IDs on different Pages.

The backend uses the existing User session to read
`GET /me/accounts?fields=id,access_token,tasks`, with cursor pagination, and
selects the requested Page with `ANALYZE` access. Its Page token stays local to
the request, inherits the User session expiry, and uses the existing Graph
client's Bearer authentication and `appsecret_proof`. Neither Page tokens nor
external IDs are stored or returned. It reads `GET /VIDEO_ID?fields=id,from`,
checks the returned video ID and owning Page, then calls
`GET /VIDEO_ID/video_insights?metric=...&period=lifetime`.

| Common field | Video insight | Reel insight |
| --- | --- | --- |
| `view_count` | `total_video_views` | `fb_reels_total_plays` |
| `like_count` | `total_video_reactions_by_type_total.like` | `post_video_likes_by_reaction_type.REACTION_LIKE` |
| `comment_count` | `total_video_stories_by_action_type.comment` | `post_video_social_actions.COMMENT` |
| `share_count` | `total_video_stories_by_action_type.share` | `post_video_social_actions.SHARE` |

These are lifetime provider counts. Regular video views use Meta's three-second
(or nearly full length for shorter videos) definition; Reel total plays include
replays. They are not directly comparable view definitions. Only explicit like
reactions map to likes; other reactions are not summed. Missing insights,
missing breakdown keys, empty values, and explicit nulls remain null; zero stays
zero. No reach, watch time, ad-account insights, or inferred counts are added.
Video totals may include promoted distribution; they are not labelled organic-only.

The response contains `video_id`, `performance_source: "facebook"` and the four
common `performance_metrics` fields. The existing `save_performance` repository
flow writes/refreshes the snapshot by internal UUID. `GET
/api/videos/VIDEO_UUID/analysis` returns the persisted snapshot. Facebook adds no schema changes; apply all migrations for the current backend. The one-snapshot-per-video rule applies:
a refresh replaces the Facebook counts, while another provider's snapshot
returns 409. A missing UUID returns 404 before Graph calls. Missing Page access
returns 403, a video/Page mismatch or entirely unavailable counts returns 422,
expired authorization returns 401, provider failures return 502, and database
failures return 503. Failures do not overwrite the previous snapshot.

Documentation verified on 2026-09-26:

- [Video insights guide](https://developers.facebook.com/docs/video-api/guides/insights/): Page token, `ANALYZE`, and `pages_read_engagement`; personal-profile/group video insights are unavailable.
- [Video insights reference and Reel metrics](https://developers.facebook.com/docs/graph-api/reference/video/video_insights/): endpoint, metric names, lifetime period and definitions. Its requirements list `read_insights` and `pages_manage_engagement`, while the guide above specifies `pages_read_engagement`. The login allowlist accepts optional `pages_manage_engagement` to accommodate the reference without requiring it for existing Instagram connections. For Facebook setup, include it in the dashboard login configuration, obtain any required Advanced Access, and reconnect. This permission allows broader Page actions, but this backend only performs GET requests. Actual app-specific requirements still need live validation; authorization failures are surfaced rather than treated as missing counts.
- [Manage Pages](https://developers.facebook.com/documentation/pages-api/manage-pages/): User-token `/me/accounts`, Page tokens and tasks. The existing login includes `pages_show_list`, `pages_read_engagement` and `read_insights`.
- [Video fields](https://developers.facebook.com/docs/graph-api/reference/video/): `id` and `from` for video identity and ownership.

Run `cd backend && TEST_DATABASE_URL=YOUR_DISPOSABLE_DATABASE .venv/bin/python -m unittest discover -s tests -p 'test_facebook*.py'`
for mocked Graph mapping/authentication/error checks plus real PostgreSQL
API/repository round trips for both media kinds. Database tests are skipped
without `TEST_DATABASE_URL`. Live metrics still require configured Meta
credentials, a browser-authorized session, Page access, and a real Page video
or Reel; fixtures cannot establish live permissions or provider availability.

## Attach Meta Ads metrics (Facebook and Instagram)

Apply migration **004** before starting the updated backend. With the existing
Meta session cookie, send:

```http
POST /api/meta/ads/META_AD_ID/metrics
Content-Type: application/json

{"video_id":"INTERNAL_VIDEO_UUID","since":"2026-09-01","until":"2026-09-20"}
```

The path is a numeric **ad ID**, not a creative, campaign, ad set, or public-post
ID. The caller selects the matching internal video UUID; this does not compare
creative content with the uploaded video. Use the same ad ID when refreshing.
The existing User access token needs `ads_read` (already in the login setup)
and access to the ad account. Apps serving other businesses may require
Advanced Access/App Review. No additional OAuth scopes are introduced.

The client checks `GET /AD_ID?fields=id,account_id`, then reads
`GET /AD_ID/insights` at `level=ad` for the explicit date range with
`time_increment=all_days`. It requests one aggregate across all placements:
Facebook-only, Instagram-only, and mixed-placement ads use the same endpoint.
If an ad also ran on other Meta placements, those are included in the total.
There is no placement breakdown or summing of reach, rates, or action types.

Attribution is explicitly requested as `7d_click` and `1d_view`, with
`action_report_time=impression` and actions broken down by `action_type`.
Dates use Meta's ad-account reporting calendar. These settings are saved with
the result; reporting can differ from Ads Manager when its settings differ.
An empty report or a report containing no metric values returns 422 and does
not overwrite the prior snapshot. Permission/rate-limit/provider errors return
502; expired authorization returns 401. Unknown UUIDs return 404 and an existing
snapshot from another provider returns 409 before fetching. Additional rows,
pagination, or a mismatched ad/account/date range fail rather than being combined.

The response and persisted analysis use `performance_source: "meta_ads"`.
The four common counts remain present. `view_count` uses only the `video_view`
action value (three-second views); plays and impressions are not substituted.
Likes/comments/shares remain null, while all reported action types are retained
in `performance_metrics.meta_ads`:

| Field | Meaning / normalized representation |
| --- | --- |
| `impressions` | Ad displays; integer or null |
| `reach` | People reached, as reported by Meta; integer or null, not summed across placements |
| `clicks` | All ad clicks, not just link clicks; integer or null |
| `spend` | Spend in `account_currency`; exact decimal string or null |
| `ctr` | Meta's all-click CTR percentage; decimal string or null |
| `cpc` | Meta's all-click cost per click in `account_currency`; decimal string or null |
| `actions`, `conversions` | Lists of action types with exact decimal `value`, `7d_click`, and `1d_view` values; missing values are null |
| `video_play_actions` | Provider video-play action stats, kept separately from three-second views |
| `account_currency` | Currency code or null; no assumed currency or conversion |
| `date_start`, `date_stop` | Validated reporting dates |
| `action_report_time`, `action_attribution_windows` | Requested reporting/attribution settings |

Explicit zeros remain zero (decimal values remain strings); absent metrics and
arrays remain null. Explicit empty arrays remain empty arrays. Fractional
modeled conversions are preserved. Rates are not recomputed. Overlapping action
types and attribution windows are never added together into a conversion total.
Provider IDs, tokens, and unrelated response fields are excluded from storage.

The existing repository saves and refreshes the single snapshot by internal
UUID and returns it through `GET /api/videos/VIDEO_UUID/analysis`. A refresh
replaces the prior period/values, including newly unavailable values with null;
it does not accumulate historical reporting periods. Migration 004 adds one
nullable JSONB column and permits ad-only snapshots without organic counts.
Both `save_analysis` and `save_performance` preserve the extended metrics.

Official references checked on 2026-09-26:

- [Ads Insights API](https://developers.facebook.com/docs/marketing-api/insights/): ad-level endpoint, access permission, reporting options.
- [Instagram ad insights](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/get-ad-insights.md): same Insights API for Facebook/Instagram delivery; placement breakdown is optional.
- [Ad reference](https://developers.facebook.com/docs/marketing-api/reference/adgroup/): ad identity and account relationship.
- [Action stats reference](https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/): action types including `video_view` (three-second views).
- Meta's official current [Insights fields/types](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adsinsights.py) and [ad Insights request parameters](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/ad.py) were checked because several old Insights field-reference URLs returned unavailable pages. The SDK is a reference only; it is not an added dependency.

Tests use mocked Graph responses and a real PostgreSQL round trip when
`TEST_DATABASE_URL` is provided. They cover migration of existing snapshots,
partial/non-video ad data, exact decimals and nulls, UUID isolation, refresh,
error preservation, cascade deletion, and both repository write entry points.
Live ad access/metric availability still requires an authorized Meta account;
mock tests do not verify that access. No frontend or system-prompt changes are
included.

## Browse Meta content

Connect Meta in the frontend and choose named business accounts. All account
pages are discovered before a sole account in each source category is selected
automatically. Multiple Pages, linked Instagram accounts, and ad accounts can be
selected together. Content cards distinguish organic videos from paid ads.

The frontend uses account discovery below and the future
[library contract](frontend/LIBRARY_CONTRACT.md) for content, processing status,
sync, and batch recommendations. It does not ask for matching uploads or IDs.

Read-only discovery routes under `/api/meta/discovery`:

- `GET /pages`
- `GET /pages/{page_id}/instagram-accounts`
- `GET /pages/{page_id}/facebook/{reels|videos}`
- `GET /pages/{page_id}/instagram/{account_id}/media`
- `GET /ad-accounts`
- `GET /ad-accounts/{account_id}/ads`

Lists return `{items, next_cursor}` and accept `?after=` (except the single
linked Instagram-account lookup). Items contain only selection labels, internal
IDs, optional thumbnails/dates/status, and type. Discovery does not call insights.
Graph pagination URLs and Page tokens stay on the backend. Page discovery uses
the existing request-local Page client and its ANALYZE access requirement.
Permission errors return 403, disconnected sessions 401, provider errors 502.
The existing metric endpoints above remain available for programmatic use;
the new library frontend does not call these per-video metric endpoints.

Reference: Meta's official [Page SDK edges](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py)
and [Instagram account discovery example](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).
No SDK dependency, migration, analysis logic, or prompt changes are needed.
Mocked tests do not establish live access to a particular business's assets.
