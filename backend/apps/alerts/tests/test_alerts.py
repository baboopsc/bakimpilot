from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.services import Problem, sync_alerts
from apps.alerts.tasks import run_due_check
from apps.fleet.tests.factories import AircraftFactory
from apps.maintenance.models import MaintenanceRule
from apps.maintenance.services import record_compliance

pytestmark = pytest.mark.django_db
DUE_KINDS = {Alert.Kind.DUE_SOON, Alert.Kind.OVERDUE}


def p(key="k1", kind=Alert.Kind.DUE_SOON, severity=Alert.Severity.WARNING):
    return Problem(key=key, kind=kind, severity=severity, title=key)


def test_sync_is_idempotent():
    assert sync_alerts([p()], kinds=DUE_KINDS).opened == 1
    again = sync_alerts([p()], kinds=DUE_KINDS)
    assert (again.opened, again.updated, again.resolved) == (0, 0, 0)
    assert Alert.objects.count() == 1


def test_escalation_reraises_and_clears_acknowledgement(planner):
    sync_alerts([p()], kinds=DUE_KINDS)
    Alert.objects.update(acknowledged_at=timezone.now(), acknowledged_by=planner)
    res = sync_alerts([p(kind=Alert.Kind.OVERDUE, severity=Alert.Severity.CRITICAL)], kinds=DUE_KINDS)
    assert res.updated == 1
    alert = Alert.objects.get()
    assert alert.kind == Alert.Kind.OVERDUE and alert.acknowledged_at is None


def test_problem_gone_resolves_alert_but_other_kinds_untouched():
    sync_alerts([p("stock", kind=Alert.Kind.LOW_STOCK)], kinds={Alert.Kind.LOW_STOCK})
    sync_alerts([p()], kinds=DUE_KINDS)
    res = sync_alerts([], kinds=DUE_KINDS)
    assert res.resolved == 1
    assert Alert.objects.get(dedup_key="stock").resolved_at is None


def test_due_check_task_end_to_end(planner, tech_client):
    ac = AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=31))
    rule = MaintenanceRule.objects.create(
        code="R", name="30 day", applies_to="AIRCRAFT_MODEL", aircraft_model="TB2", interval_days=30
    )
    assert run_due_check.delay().get()["opened"] == 1  # runs eagerly in tests
    alert = Alert.objects.get()
    assert alert.severity == Alert.Severity.CRITICAL and alert.aircraft == ac

    res = tech_client.post(f"/api/alerts/{alert.pk}/acknowledge/")
    assert res.status_code == 200 and res.data["acknowledged_by"] == "technician"

    record_compliance(actor=planner, rule=rule, aircraft=ac)
    assert run_due_check()["resolved"] == 1


def test_viewer_cannot_acknowledge(viewer_client):
    sync_alerts([p()], kinds=DUE_KINDS)
    alert = Alert.objects.get()
    assert viewer_client.post(f"/api/alerts/{alert.pk}/acknowledge/").status_code == 403
    assert viewer_client.get("/api/alerts/?resolved_at__isnull=true").data["count"] == 1
