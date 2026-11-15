# Deploying BakımPilot

The production setup is the same `docker-compose.yml` used locally, plus
`docker-compose.prod.yml`, which adds **Caddy** for HTTPS and stops exposing
internal ports. Any Linux VM with Docker works (e.g. a 2 vCPU / 4 GB VPS).

```
Internet ──443──▶ Caddy ──▶ web (Next.js :3000) ──/api──▶ api (Django/gunicorn :8000)
                    └──/admin, /static──────────────────▶ api
                                     api, worker, beat ──▶ db (PostgreSQL + pgvector), redis
```

## First deployment

1. Point a DNS `A` record (e.g. `bakimpilot.example.com`) to the server's IP.
2. On the server (Docker + Compose plugin installed):
   ```bash
   git clone <your repo> bakimpilot && cd bakimpilot
   cp .env.example .env
   # edit .env: DJANGO_SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(50))"),
   #            POSTGRES_PASSWORD, DOMAIN, optionally LLM_PROVIDER=anthropic + LLM_API_KEY
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   docker compose run --rm api python manage.py createsuperuser   # or seed_demo for a demo
   ```
3. Open `https://<DOMAIN>`. Caddy obtains a Let's Encrypt certificate automatically.

## Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
The one-shot `migrate` service applies new migrations before `api`, `worker`
and `beat` start.

## Operations checklist

- **Backups:** `docker compose exec db pg_dump -U bakimpilot bakimpilot | gzip > backup-$(date +%F).sql.gz`
  daily (cron) and copy off the server. Also back up the `media` volume (uploaded manuals).
- **Only one `beat`** container may run, or scheduled checks would fire twice.
- **Counter integrity:** `docker compose exec api python manage.py verify_counters`
  (exits non-zero on drift; can run from cron).
- **Logs:** `docker compose logs -f api worker`.
- **Secrets** live only in `.env` on the server, never in git.
