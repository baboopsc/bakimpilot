from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.dashboard.views import readiness, timeline
from apps.fleet import services as fleet
from apps.fleet.models import Aircraft
from apps.fleet.tests.factories import AircraftFactory
from apps.maintenance import engine
from apps.maintenance.models import MaintenanceRule

pytestmark = pytest.mark.django_db


def status(ac_id, s):
    return engine.AirworthinessStatus(ac_id, f"T{ac_id}", s, [], 0, 0)


def test_readiness_excludes_stored_aircraft_and_counts_attention_as_ready():
    statuses = [
        status(1, engine.AIRWORTHY),
        status(2, engine.ATTENTION),
        status(3, engine.GROUNDED),
        status(4, engine.GROUNDED),
    ]
    r = readiness(statuses, active_ids={1, 2, 3})  # 4 is stored
    assert r["active_aircraft"] == 3 and r["ready"] == 2 and r["readiness_pct"] == 66.7


def test_readiness_with_no_aircraft_is_none_not_division_error():
    assert readiness([], set())["readiness_pct"] is None


def test_timeline_keeps_next_30_days_and_pins_overdue_to_today():
    today = date(2026, 3, 1)

    def item(key, st, when):
        i = engine.DueItem(key=key, kind="RULE", title=key, aircraft_id=1, tail_number="T1")
        i.measures.append(engine.Measure("days", 10, 0, 0, st, when))
        return i

    out = timeline(
        [
            item("late", engine.OVERDUE, date(2026, 2, 1)),
            item("soon", engine.DUE_SOON, date(2026, 3, 20)),
            item("far", engine.OK, date(2026, 6, 1)),
        ],
        today,
    )
    assert [(x["key"], x["date"]) for x in out] == [("late", today), ("soon", date(2026, 3, 20))]


def test_dashboard_endpoint(viewer_client):
    ok = AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=5))
    AircraftFactory(
        model="TB2", in_service_date=timezone.localdate() - timedelta(days=40)
    )  # 30-day check overdue
    AircraftFactory(model="TB2", status=Aircraft.Status.STORED)
    MaintenanceRule.objects.create(
        code="R", name="30 day", applies_to="AIRCRAFT_MODEL", aircraft_model="TB2", interval_days=30
    )
    start = timezone.now() - timedelta(days=1)
    fleet.log_flight(actor=None, aircraft=ok, takeoff_at=start, landing_at=start + timedelta(hours=2))

    data = viewer_client.get("/api/dashboard/").data
    assert data["readiness"]["active_aircraft"] == 2
    assert data["readiness"]["readiness_pct"] == 50.0
    assert data["due_counts"]["OVERDUE"] >= 1
    assert any(t["status"] == "OVERDUE" for t in data["timeline"])
    assert sum(float(d["hours"]) for d in data["flight_hours_30d"]) == 2.0
