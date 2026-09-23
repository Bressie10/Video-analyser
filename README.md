# Video Analyzer

Minimal local development scaffold for a React frontend and FastAPI backend.

Video processing requires `ffmpeg` and `ffprobe` to be installed and available
on your shell `PATH`.

## Run locally

Frontend:

```sh
cd frontend
npm run dev
```

Backend:

```sh
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

The frontend entry point is `frontend/src/main.tsx`. The API entry point is
`backend/app/main.py`; `GET /health` returns a liveness response. Select a
supported video in the frontend and submit the form to send it to
`POST /api/videos`. Videos are capped at 500 MiB and 10 minutes, normalised to
MP4/H.264/AAC (maximum 1,920 pixels per dimension), then have mono 16 kHz PCM
WAV audio extracted during the request. Processed files are temporary and are
not retained yet.
