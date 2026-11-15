import pytest
from django.conf import settings

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def test_login_returns_access_and_sets_httponly_refresh_cookie(anon_client, planner):
    res = anon_client.post("/api/auth/login/", {"username": "planner", "password": "Str0ng-pass!"})
    assert res.status_code == 200
    assert "access" in res.data
    assert "refresh" not in res.data  # never exposed to JavaScript
    assert res.data["user"]["role"] == Role.PLANNER
    cookie = res.cookies[settings.REFRESH_COOKIE_NAME]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"


def test_wrong_password_is_rejected(anon_client, planner):
    res = anon_client.post("/api/auth/login/", {"username": "planner", "password": "nope"})
    assert res.status_code == 401


def test_refresh_uses_cookie_and_old_token_is_revoked_after_logout(anon_client, planner):
    anon_client.post("/api/auth/login/", {"username": "planner", "password": "Str0ng-pass!"})
    res = anon_client.post("/api/auth/refresh/")
    assert res.status_code == 200 and "access" in res.data

    refresh = anon_client.cookies[settings.REFRESH_COOKIE_NAME].value
    anon_client.post("/api/auth/logout/")
    anon_client.cookies[settings.REFRESH_COOKIE_NAME] = refresh  # attacker replays the stolen cookie
    assert anon_client.post("/api/auth/refresh/").status_code == 401


def test_access_token_authenticates_requests(anon_client, viewer):
    res = anon_client.post("/api/auth/login/", {"username": "viewer", "password": "Str0ng-pass!"})
    anon_client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    me = anon_client.get("/api/auth/me/")
    assert me.status_code == 200 and me.data["username"] == "viewer"


def test_api_requires_authentication(anon_client):
    assert anon_client.get("/api/audit-log/").status_code == 401


@pytest.mark.parametrize("client_fixture", ["planner_client", "tech_client", "viewer_client"])
def test_only_admin_manages_users(request, client_fixture):
    client = request.getfixturevalue(client_fixture)
    assert client.get("/api/users/").status_code == 403


def test_admin_creates_user_with_hashed_password_and_audit_entry(admin_client):
    res = admin_client.post(
        "/api/users/", {"username": "ayse", "password": "Hangar-2026!", "role": Role.TECHNICIAN}
    )
    assert res.status_code == 201
    assert "password" not in res.data
    user = User.objects.get(username="ayse")
    assert user.check_password("Hangar-2026!") and user.password != "Hangar-2026!"
    assert AuditLog.objects.filter(action="user.created", entity_id=str(user.pk)).exists()


def test_deleting_a_user_only_deactivates(admin_client, technician):
    assert admin_client.delete(f"/api/users/{technician.pk}/").status_code == 204
    technician.refresh_from_db()
    assert technician.is_active is False
