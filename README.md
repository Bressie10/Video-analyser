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
`backend/app/main.py`; `GET /health` returns a liveness response. Select a
supported video in the frontend and submit the form to send it to
`POST /api/videos`. Videos are capped at 500 MiB and 10 minutes, normalised to
MP4/H.264/AAC (maximum 1,920 pixels per dimension), then have mono 16 kHz PCM
WAV audio extracted during the request. Processed files are temporary and are
not retained yet.

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
videos or evaluate performance metrics that are not present in that record.
Send runtime keys over HTTPS and exclude this header from proxy request logs.
