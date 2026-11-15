# BakımPilot

Maintenance & airworthiness management (MRO) for a UAV fleet. Components have
life limits in flight hours, cycles and calendar days; BakımPilot tracks them
automatically from flight logs, computes what is due or overdue, decides each
aircraft's airworthiness, and runs maintenance through work orders with a
two-person digital sign-off. An AI assistant answers from uploaded maintenance
manuals with page citations, turns plain-language questions (Turkish or
English) into safe queries, and explains statistically detected anomalies in
flight data. It runs fully offline with a deterministic mock, or with Claude.

**Stack:** Django 5.2 + DRF · PostgreSQL + pgvector · Celery + Redis ·
Next.js 16 + TypeScript + TanStack Query · JWT (httpOnly refresh cookie) ·
pytest, Vitest, Playwright · Docker Compose · GitHub Actions.

- Why every choice was made: [`docs/decisions.md`](docs/decisions.md)
- How to deploy: [`docs/deploy.md`](docs/deploy.md)

## Quick start (Docker)

```bash
cp .env.example .env        # set DJANGO_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d --build
docker compose run --rm api python manage.py seed_demo
```
Open http://localhost:3000 and log in as `planner` / `BakimPilot2026!`
(other demo users: `admin`, `tech`, `tech2`, `viewer`). API docs: http://localhost:8000/api/docs/

## Development setup (without Compose)


```bash
# Postgres (with pgvector) + Redis
docker run -d --name bakimpilot-db -e POSTGRES_USER=bakimpilot -e POSTGRES_PASSWORD=bakimpilot \
  -e POSTGRES_DB=bakimpilot -p 5432:5432 pgvector/pgvector:pg17
docker run -d --name bakimpilot-redis -p 6379:6379 redis:7-alpine

cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use .venv/bin/activate on Linux/macOS
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
pytest
```

API docs (Swagger): http://localhost:8000/api/docs/

## Demo data

```bash
python manage.py seed_demo --reset   # wipes the DB, then builds a demo fleet
```
Users: `admin`, `planner`, `tech`, `tech2`, `viewer`, all with password `BakimPilot2026!` (demo only).

## Run the frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000 (proxies /api to Django on :8000)
```

## Tests

| What | Command | Where |
|---|---|---|
| Backend unit/integration (real Postgres) | `cd backend && pytest` | 114 tests |
| Frontend unit | `cd frontend && npm test` | Vitest |
| End-to-end (real browser, real stack) | `cd frontend && npm run e2e` | Playwright |
| Counter integrity on live data | `python manage.py verify_counters` | |
