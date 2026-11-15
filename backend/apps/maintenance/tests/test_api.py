from datetime import timedelta

import pytest
from django.utils import timezone

from apps.fleet.tests.factories import AircraftFactory, PartTypeFactory
from apps.maintenance.models import MaintenanceRecord

pytestmark = pytest.mark.django_db


def test_planner_creates_rule_and_model_validation_applies(planner_client):
    ok = planner_client.post(
        "/api/maintenance-rules/",
        {
            "code": "R1",
            "name": "50h",
            "applies_to": "AIRCRAFT_MODEL",
            "aircraft_model": "TB2",
            "interval_hours": "50",
        },
        format="json",
    )
    assert ok.status_code == 201, ok.data

    no_interval = planner_client.post(
        "/api/maintenance-rules/",
        {"code": "R2", "name": "x", "applies_to": "AIRCRAFT_MODEL", "aircraft_model": "TB2"},
        format="json",
    )
    assert no_interval.status_code == 400

    mixed = planner_client.post(
        "/api/maintenance-rules/",
        {
            "code": "R3",
            "name": "x",
            "applies_to": "AIRCRAFT_MODEL",
            "aircraft_model": "TB2",
            "part_type": PartTypeFactory().pk,
            "interval_days": 30,
        },
        format="json",
    )
    assert mixed.status_code == 400


def test_technician_cannot_create_rules(tech_client):
    res = tech_client.post(
        "/api/maintenance-rules/",
        {
            "code": "R1",
            "name": "x",
            "applies_to": "AIRCRAFT_MODEL",
            "aircraft_model": "TB2",
            "interval_days": 1,
        },
        format="json",
    )
    assert res.status_code == 403


def test_due_list_and_airworthiness_endpoints(planner_client, viewer_client):
    ac = AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=40))
    planner_client.post(
        "/api/maintenance-rules/",
        {
            "code": "R1",
            "name": "30 day check",
            "applies_to": "AIRCRAFT_MODEL",
            "aircraft_model": "TB2",
            "interval_days": 30,
        },
        format="json",
    )
    due = viewer_client.get("/api/due-items/?status=OVERDUE").data
    assert len(due) == 1 and due[0]["tail_number"] == ac.tail_number
    assert due[0]["measures"][0]["unit"] == "days"

    aw = viewer_client.get(f"/api/airworthiness/?aircraft={ac.pk}").data
    assert aw[0]["status"] == "GROUNDED"

    # baseline entry clears it
    rule_id = due[0]["rule_id"]
    res = planner_client.post(
        "/api/maintenance-records/", {"rule": rule_id, "aircraft": ac.pk}, format="json"
    )
    assert res.status_code == 201, res.data
    assert MaintenanceRecord.objects.count() == 1
    assert viewer_client.get("/api/airworthiness/").data[0]["status"] == "AIRWORTHY"
