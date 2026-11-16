#!/usr/bin/env bash
# Start command for the free Render demo (D-034).
# Render's free plan has no pre-deploy hook, so migrations and the demo seed
# run here, before gunicorn binds the port. Both are idempotent: safe on every
# boot, including the cold starts after the free instance has slept.
set -euo pipefail

python manage.py migrate --noinput   # also runs CREATE EXTENSION vector (apps/ai/migrations/0001)

if [ "${DEMO_RESET_ON_START:-false}" = "true" ]; then
  python manage.py seed_demo --reset   # wipe visitors' changes on every boot
else
  python manage.py seed_demo --if-empty
fi

# 2 sync workers fit in the free plan's 512 MB. Long timeout: eager Celery
# tasks (PDF ingestion) run inside the request on this deployment.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile -
