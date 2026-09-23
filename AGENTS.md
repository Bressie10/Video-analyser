Project

Build a TikTok video analyser that analyses video content and performance, returns useful stats, and uses the results to recommend future video ideas and scripts.

## Project structure

- `backend/app/main.py` — FastAPI application entry point.
- `backend/requirements.txt` — Python dependencies.
- `frontend/src/main.tsx` — React application entry point.
- `frontend/index.html` — Frontend HTML entry point.
- `frontend/package.json` — Frontend scripts and dependencies.
- `frontend/vite.config.ts` — Vite configuration.
- `README.md` — Project setup information.

Tech Stack
Frontend: React + TypeScript
Backend: FastAPI + Python
Video/ML analysis: PyTorch
Database: PostgreSQL
Development Rules
Inspect existing code before making changes.
Keep changes focused on the requested task.
Do not refactor unrelated code.
Do not add dependencies unless necessary.
Follow existing project structure and conventions.
Add or update tests for changed behaviour.
For bugs, reproduce the issue before editing and verify it is fixed afterward.

Testing
Run the smallest set of checks that fully covers the change.
React: lint, type check, relevant tests, build, and UI verification when needed.
FastAPI: lint, relevant unit/API tests, and verify affected requests/responses.
PostgreSQL: verify migrations, schema changes, and affected queries.
PyTorch/video analysis: test preprocessing and outputs with a known sample.
Cross-stack changes: test the full affected flow from frontend → API → database/analysis → UI.

Change Summary
For every change, report:
Files changed
Behaviour changed
Tests/checks run
Risks
Assumptions
Anything not tested
