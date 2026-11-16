"""
BakımPilot settings.

Every value that differs between laptop, CI and production is read from
environment variables (12-factor style), so the same code runs everywhere.
See docs/decisions.md (D-003).
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# A local .env file is optional; real deployments inject env vars directly.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key-change-me-0123456789abcdef")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Render sets this to the service's public hostname (e.g. bakimpilot-api.onrender.com). D-034.
if RENDER_HOST := env("RENDER_EXTERNAL_HOSTNAME", default=""):
    ALLOWED_HOSTS.append(RENDER_HOST)
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    # ours
    "apps.accounts",
    "apps.audit",
    "apps.fleet",
    "apps.maintenance",
    "apps.workorders",
    "apps.inventory",
    "apps.alerts",
    "apps.dashboard",
    "apps.ai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves admin/static files from gunicorn
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL only (pgvector is needed for the RAG assistant). D-002.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://bakimpilot:bakimpilot@localhost:5432/bakimpilot",
    )
}
# Reuse DB connections for a minute instead of opening one per request (matters
# with a remote managed DB like Neon, where each TLS handshake costs ~50-100 ms).
# Health checks drop a connection the server closed meanwhile (Neon scales to zero).
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True  # store UTC in the DB, convert at the edges

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- REST framework -------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Secure by default: every endpoint needs a logged-in user unless it
    # explicitly says otherwise. Role checks are layered on top per view.
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.accounts.permissions.RoleBasedPermission",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "config.exceptions.exception_handler",
    "DEFAULT_THROTTLE_RATES": {"login": env("LOGIN_THROTTLE", default="10/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "BakımPilot API",
    "DESCRIPTION": "UAV fleet maintenance & airworthiness management",
    "VERSION": "1.0.0",
}

# Short-lived access token kept in memory by the frontend; long-lived refresh
# token in an httpOnly cookie that JavaScript can't read. D-005.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
REFRESH_COOKIE_NAME = "bp_refresh"
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", default=not DEBUG)

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# --- Celery ---------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
# Eager mode runs every .delay() inline in the calling process: no Redis, no
# worker. Used by the free demo deployment and by tests; Docker Compose keeps
# the real broker + worker + beat. Trade-offs are in D-035.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULE = {
    "due-check-hourly": {
        "task": "apps.alerts.tasks.run_due_check",
        "schedule": crontab(minute=0),
    },
    "anomaly-scan-daily": {
        "task": "apps.ai.tasks.run_anomaly_scan",
        "schedule": crontab(minute=30, hour=6),
    },
    "stock-check-daily": {
        "task": "apps.alerts.tasks.run_stock_check",
        "schedule": crontab(minute=15, hour=6),
    },
}

# --- Domain settings ------------------------------------------------------
# An item is "due soon" when it has used up this share of its interval.
MAINTENANCE_DUE_SOON_RATIO = env.float("MAINTENANCE_DUE_SOON_RATIO", default=0.9)

# Shared secret for the flight-data ingestion service (empty = ingestion disabled).
INGEST_TOKEN = env("INGEST_TOKEN", default="")

# --- AI -------------------------------------------------------------------
# auto (default) = Claude when an API key is set, otherwise the offline mock. D-036.
LLM_PROVIDER = env("LLM_PROVIDER", default="auto")  # auto | mock | anthropic
LLM_MODEL = env("LLM_MODEL", default="")
LLM_API_KEY = env("LLM_API_KEY", default="") or env("ANTHROPIC_API_KEY", default="")
LLM_BASE_URL = env("LLM_BASE_URL", default="")
EMBEDDING_PROVIDER = env("EMBEDDING_PROVIDER", default="mock")  # mock (see D-023)
EMBEDDING_DIM = 384  # fixed: it is baked into the database column (D-023)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# HTTPS redirect and HSTS are done by the platform in front of Django (Caddy on
# the VM, deploy/Caddyfile; Render's edge on the free demo), so Django's own
# versions of those checks are silenced.
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
