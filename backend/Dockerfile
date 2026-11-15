# ---- BakımPilot API (Django + gunicorn); the same image runs Celery worker/beat ----
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files are collected at build time (served by WhiteNoise).
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/media && chown -R app /app/media
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health/').status==200 else 1)"

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
