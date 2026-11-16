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
Next.js 16 + TypeScript + TanStack Query · Go (flight-data ingestion) · JWT (httpOnly refresh cookie) ·
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

## Deploy (free live demo)

Free hosting for a public demo: **Neon** (PostgreSQL + pgvector), **Render** (Django API),
**Vercel** (Next.js). Why this split and its limits: D-034 to D-037 in `docs/decisions.md`.
For a single-server production setup with the full Celery stack, see `docs/deploy.md`.

```
Browser ──▶ Vercel (Next.js) ──/api/* rewrite──▶ Render (Django + gunicorn) ──▶ Neon (Postgres + pgvector)
```

**1. Neon (database)**
1. Sign up at https://neon.tech → **New Project** → name `bakimpilot`, Postgres 17, region *AWS Europe (Frankfurt)*.
2. Dashboard → **Connect** → turn **Connection pooling off** (migrations need a direct connection) →
   copy the connection string. It looks like
   `postgresql://neondb_owner:…@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
3. Nothing else: the first migration runs `CREATE EXTENSION vector` itself.

**2. Render (API)**
1. Sign up at https://render.com with GitHub → **New → Blueprint** → pick this repository.
   Render reads `render.yaml` and proposes the `bakimpilot-api` web service (free plan).
2. Fill in the values it asks for:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `CORS_ALLOWED_ORIGINS` | your Vercel URL, e.g. `https://bakimpilot.vercel.app` (no trailing `/`) |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | same Vercel URL |
   | `LLM_API_KEY` | optional Anthropic key; leave empty for the offline mock AI |

   Leave the Vercel ones as a placeholder (`https://example.com`) if you don't know the URL yet and update them after step 3.
3. **Apply**. On every start the service runs `migrate` and `seed_demo --if-empty`, then gunicorn.
   Check `https://<service>.onrender.com/api/health/` → `{"status": "ok"}`.

**3. Vercel (frontend)**
1. Sign up at https://vercel.com with GitHub → **Add New → Project** → import this repository.
2. **Root Directory:** `frontend` (framework is detected as Next.js).
3. **Environment Variables:** `NEXT_PUBLIC_API_URL` = `https://<service>.onrender.com` (no trailing `/`).
   It is read at **build time**; after changing it, redeploy.
4. **Deploy**. Then put the final Vercel URL into Render's `CORS_ALLOWED_ORIGINS` and
   `DJANGO_CSRF_TRUSTED_ORIGINS` (Render → service → **Environment** → Save, which restarts it).
5. Open the Vercel URL → **Try the demo (one click)**.

**Notes**
- The free Render instance sleeps after ~15 min idle. The first request then takes about a minute.
- Without Redis, Celery tasks run inline (`CELERY_TASK_ALWAYS_EAGER=true`) and the scheduled beat jobs don't run (D-035).
- To wipe visitors' changes, set `DEMO_RESET_ON_START=true` on Render for one restart, then set it back to `false`.
- Every push to `main` redeploys both services automatically.

## Tests

| What | Command | Where |
|---|---|---|
| Backend unit/integration (real Postgres) | `cd backend && pytest` | 122 tests |
| Frontend unit | `cd frontend && npm test` | Vitest |
| Go ingestion service | `cd ingest && go test ./...` | 7 tests |
| End-to-end (real browser, real stack) | `cd frontend && npm run e2e` | Playwright |
| Counter integrity on live data | `python manage.py verify_counters` | |
