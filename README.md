# BakımPilot

Maintenance & airworthiness management (MRO) for a UAV fleet: life-limited
components, flight-hour/cycle accumulation, a maintenance rule engine, work
orders with digital sign-off, spare parts, and AI assistance.

Design decisions and their trade-offs: [`docs/decisions.md`](docs/decisions.md).

## Run the backend locally

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
