from decimal import Decimal

import pytest

from apps.fleet.models import Component

from .factories import AircraftFactory, PartTypeFactory

pytestmark = pytest.mark.django_db


def test_planner_registers_aircraft_and_counters_start_at_initial_usage(planner_client):
    res = planner_client.post(
        "/api/aircraft/",
        {
            "tail_number": "TB2-T001",
            "model": "TB2",
            "serial_number": "X1",
            "in_service_date": "2025-05-01",
            "initial_hours": "12.5",
        },
    )
    assert res.status_code == 201, res.data
    assert Decimal(res.data["total_hours"]) == Decimal("12.5")


def test_counters_cannot_be_set_through_the_api(planner_client):
    ac = AircraftFactory()
    planner_client.patch(f"/api/aircraft/{ac.pk}/", {"total_hours": "9999"})
    ac.refresh_from_db()
    assert ac.total_hours == 0


@pytest.mark.parametrize("client_fixture", ["viewer_client", "tech_client"])
def test_viewer_and_technician_cannot_register_aircraft(request, client_fixture):
    client = request.getfixturevalue(client_fixture)
    res = client.post(
        "/api/aircraft/",
        {"tail_number": "X", "model": "TB2", "serial_number": "Y", "in_service_date": "2025-01-01"},
    )
    assert res.status_code == 403


def test_full_install_fly_remove_flow_over_http(planner_client, tech_client):
    ac = AircraftFactory()
    pt = PartTypeFactory()
    comp = planner_client.post(
        "/api/components/", {"part_type": pt.pk, "serial_number": "E-1", "manufacture_date": "2025-01-01"}
    ).data

    res = planner_client.post(
        f"/api/components/{comp['id']}/install/",
        {"aircraft": ac.pk, "position": "ENGINE", "installed_at": "2026-03-01T08:00:00+03:00"},
    )
    assert res.status_code == 201, res.data
    assert res.data["installed_on"]["tail_number"] == ac.tail_number

    # technicians may log flights
    res = tech_client.post(
        "/api/flights/",
        {
            "aircraft": ac.pk,
            "takeoff_at": "2026-03-02T08:00:00+03:00",
            "landing_at": "2026-03-02T10:30:00+03:00",
        },
    )
    assert res.status_code == 201, res.data
    assert res.data["duration_hours"] == "2.50"

    assert planner_client.get(f"/api/components/{comp['id']}/").data["hours_since_new"] == "2.50"
    assert planner_client.get(f"/api/aircraft/{ac.pk}/components/").data[0]["position"] == "ENGINE"

    res = planner_client.post(f"/api/components/{comp['id']}/remove/", {"reason": "borescope finding"})
    assert res.status_code == 200
    assert res.data["installed_on"] is None
    assert len(planner_client.get(f"/api/components/{comp['id']}/history/").data) == 1


def test_domain_errors_become_400_with_code(planner_client):
    comp = Component.objects.create(
        part_type=PartTypeFactory(), serial_number="S", manufacture_date="2025-01-01"
    )
    res = planner_client.post(f"/api/components/{comp.pk}/remove/", {"reason": "x"})
    assert res.status_code == 400
    assert res.data["code"] == "not_installed"


def test_flights_are_immutable_via_api(planner_client):
    ac = AircraftFactory()
    flight = planner_client.post(
        "/api/flights/",
        {
            "aircraft": ac.pk,
            "takeoff_at": "2026-03-02T08:00:00+03:00",
            "landing_at": "2026-03-02T09:00:00+03:00",
        },
    ).data
    assert planner_client.patch(f"/api/flights/{flight['id']}/", {"cycles": 5}).status_code == 405
    assert planner_client.delete(f"/api/flights/{flight['id']}/").status_code == 405
