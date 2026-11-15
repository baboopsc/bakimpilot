"""Celery app: runs background jobs (due-checks, PDF ingestion) outside the web request."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("bakimpilot")
# Read every CELERY_* value from Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")
# Find tasks.py modules inside installed apps.
app.autodiscover_tasks()
