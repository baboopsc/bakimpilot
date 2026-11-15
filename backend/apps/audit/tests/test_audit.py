import pytest

from apps.audit.services import record

pytestmark = pytest.mark.django_db


def test_audit_rows_cannot_be_edited_or_deleted(planner):
    entry = record(planner, "test.action", planner, "something happened")
    entry.summary = "rewritten history"
    with pytest.raises(RuntimeError):
        entry.save()
    with pytest.raises(RuntimeError):
        entry.delete()


def test_audit_api_is_read_only(viewer_client, admin_client, planner):
    record(planner, "test.action", planner, "x")
    assert viewer_client.get("/api/audit-log/").data["count"] == 1
    assert admin_client.post("/api/audit-log/", {}).status_code == 405
