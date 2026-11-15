import pytest

from apps.fleet.models import FlightLog

from .factories import AircraftFactory

pytestmark = pytest.mark.django_db
TOKEN = "test-ingest-token"
BODY = {
    "external_id": "GS-TB2-T001-20260301-0800",
    "tail_number": "TB2-T001",
    "takeoff_at": "2026-03-01T08:00:00+03:00",
    "landing_at": "2026-03-01T10:30:00+03:00",
    "max_engine_temp_c": "97.4",
    "avg_vibration_g": "0.412",
    "fuel_used_l": "27.50",
}


@pytest.fixture(autouse=True)
def token(settings):
    settings.INGEST_TOKEN = TOKEN


def post(client, body=BODY, token=TOKEN):
    return client.post("/api/ingest/flights/", body, format="json", HTTP_X_INGEST_TOKEN=token)


def test_ingest_creates_flight_and_updates_counters(anon_client):
    ac = AircraftFactory(tail_number="TB2-T001")
    res = post(anon_client)
    assert res.status_code == 201, res.data
    assert res.data["source"] == "ingest" and res.data["duration_hours"] == "2.50"
    ac.refresh_from_db()
    assert str(ac.total_hours) == "2.50"


def test_retry_is_idempotent(anon_client):
    AircraftFactory(tail_number="TB2-T001")
    assert post(anon_client).status_code == 201
    assert post(anon_client).status_code == 200  # same external_id: not counted twice
    assert FlightLog.objects.count() == 1


def test_wrong_or_missing_token_rejected(anon_client, settings):
    AircraftFactory(tail_number="TB2-T001")
    assert post(anon_client, token="nope").status_code == 401
    settings.INGEST_TOKEN = ""  # ingestion disabled
    assert post(anon_client, token="").status_code == 401


def test_unknown_tail_and_domain_rules(anon_client):
    assert post(anon_client).data["code"] == "unknown_aircraft"
    AircraftFactory(tail_number="TB2-T001")
    bad = {**BODY, "landing_at": "2026-03-01T07:00:00+03:00"}
    assert post(anon_client, bad).status_code == 400  # landing before take-off, same rule as manual entry


def test_user_jwt_is_not_enough(planner_client):
    AircraftFactory(tail_number="TB2-T001")
    res = planner_client.post("/api/ingest/flights/", BODY, format="json")
    assert res.status_code == 401
