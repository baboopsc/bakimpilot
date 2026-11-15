"""Shared pytest fixtures: users of every role and logged-in API clients."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.LLM_PROVIDER = "mock"
    settings.EMBEDDING_PROVIDER = "mock"
    settings.MEDIA_ROOT = tmp_path / "media"  # uploaded test PDFs never land in the repo
    # Real password hashing is deliberately slow; tests don't need that.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def _make_user(role: str) -> User:
    return User.objects.create_user(username=role.lower(), password="Str0ng-pass!", role=role)


@pytest.fixture
def admin_user(db):
    return _make_user(Role.ADMIN)


@pytest.fixture
def planner(db):
    return _make_user(Role.PLANNER)


@pytest.fixture
def technician(db):
    return _make_user(Role.TECHNICIAN)


@pytest.fixture
def viewer(db):
    return _make_user(Role.VIEWER)


def _client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def anon_client():
    return APIClient()


@pytest.fixture
def admin_client(admin_user):
    return _client_for(admin_user)


@pytest.fixture
def planner_client(planner):
    return _client_for(planner)


@pytest.fixture
def tech_client(technician):
    return _client_for(technician)


@pytest.fixture
def viewer_client(viewer):
    return _client_for(viewer)
