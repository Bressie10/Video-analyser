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
`backend/app/main.py`; `GET /health` returns a liveness response. In the
frontend, connect TikTok, then provide a video file, its matching full TikTok
video URL, and an OpenAI API key. The form uploads to `POST /api/videos`, reads
the saved result through `GET /api/videos/{video_id}/analysis`, and requests the
idea and script through `POST /api/videos/{video_id}/recommendations`. The
runtime key is sent only with the recommendation request and is not persisted
by the frontend. Run `npm run test:e2e` from `frontend` for the browser flow
test, which uses mocked API responses. Videos are capped at 500 MiB and 10
minutes, normalised to MP4/H.264/AAC (maximum 1,920 pixels per dimension), then
have mono 16 kHz PCM WAV audio extracted during the request. Processed files
are temporary and are not retained yet.

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
only TikTok has an API integration. Missing counts are null, never assumed zero.
Uploads without performance data omit both fields. Each analyzed video still has
one count snapshot. Source IDs and URLs are not persisted.

Apply migration 003 before running the updated backend, including on existing
databases. It preserves existing TikTok snapshots and their retrieval timestamps.

To run backend checks, use `cd backend && .venv/bin/python -m unittest discover -s tests`.
Set `TEST_DATABASE_URL` to a disposable PostgreSQL database to include the
migration/repository/API test; it creates and removes an isolated test schema.
Without that variable, the database integration test is skipped.
