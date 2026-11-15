from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.fleet import services as fleet
from apps.fleet.tests.factories import AircraftFactory
from apps.maintenance import engine
from apps.maintenance.models import MaintenanceRecord, MaintenanceRule
from apps.workorders import services
from apps.workorders.models import ChecklistItem, WorkOrder
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db
PW = "Str0ng-pass!"


def fly(ac, days_ago, hours):
    start = timezone.now().replace(microsecond=0) - timedelta(days=days_ago)
    fleet.log_flight(actor=None, aircraft=ac, takeoff_at=start, landing_at=start + timedelta(hours=hours))


@pytest.fixture
def aircraft():
    return AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=60))


@pytest.fixture
def rule():
    return MaintenanceRule.objects.create(
        code="TB2-50H",
        name="50 h inspection",
        applies_to="AIRCRAFT_MODEL",
        aircraft_model="TB2",
        interval_hours=50,
        checklist=["Inspect propeller", "Check servo play", "Download flight logs"],
    )


@pytest.fixture
def wo(planner, technician, aircraft, rule):
    return services.create_work_order(
        actor=planner, aircraft=aircraft, title="50h", rule=rule, assigned_to=technician
    )


def complete_checklist(wo, tech):
    services.start(actor=tech, wo=wo)
    for item in wo.checklist.all():
        services.set_checklist_item(actor=tech, wo=wo, item_id=item.pk, done=True, note="ok")


def test_numbering_and_checklist_copied_from_rule(wo):
    assert wo.number == f"WO-{timezone.localdate():%Y}-{wo.pk:05d}"
    assert [i.text for i in wo.checklist.all()] == [
        "Inspect propeller",
        "Check servo play",
        "Download flight logs",
    ]


def test_happy_path_closes_and_resets_due_item(wo, technician, planner, aircraft, rule):
    fly(aircraft, 3, 48)  # due soon
    assert engine.compute_due_items()[0].status == engine.DUE_SOON

    complete_checklist(wo, technician)
    services.tech_sign_off(actor=technician, wo=wo, password=PW)
    fly(aircraft, 1, 2)  # flown while waiting for inspection
    services.certify(actor=planner, wo=wo, password=PW)

    wo.refresh_from_db()
    assert wo.status == WorkOrder.Status.CLOSED and services.verify_signatures(wo)
    rec = MaintenanceRecord.objects.get()
    assert rec.work_order == wo
    assert rec.hours_at == Decimal("48.00")  # counters at tech sign-off, not certification
    item = engine.compute_due_items()[0]
    assert item.status == engine.OK and item.measures[0].used == Decimal("2.00")


def test_sign_off_requires_complete_checklist(wo, technician):
    services.start(actor=technician, wo=wo)
    with pytest.raises(DomainError) as err:
        services.tech_sign_off(actor=technician, wo=wo, password=PW)
    assert err.value.code == "checklist_incomplete"


def test_sign_off_requires_correct_password(wo, technician):
    complete_checklist(wo, technician)
    with pytest.raises(DomainError) as err:
        services.tech_sign_off(actor=technician, wo=wo, password="wrong")
    assert err.value.code == "bad_signature_password"


def test_only_assignee_can_work(wo):
    other = User.objects.create_user("other_tech", password=PW, role=Role.TECHNICIAN)
    with pytest.raises(DomainError) as err:
        services.start(actor=other, wo=wo)
    assert err.value.code == "not_assignee"


def test_two_person_rule_enforced_by_service_and_database(wo, technician, admin_user):
    complete_checklist(wo, technician)
    services.tech_sign_off(actor=technician, wo=wo, password=PW)
    with pytest.raises(DomainError):
        services.certify(actor=technician, wo=wo, password=PW)  # technician role can't certify at all

    # Even an admin who was somehow also the technician can't self-certify.
    WorkOrder.objects.filter(pk=wo.pk).update(tech_signed_by=admin_user)
    wo.refresh_from_db()
    with pytest.raises(DomainError) as err:
        services.certify(actor=admin_user, wo=wo, password=PW)
    assert err.value.code == "two_person_rule"


def test_tampering_after_signature_is_detected(wo, technician, planner):
    complete_checklist(wo, technician)
    services.tech_sign_off(actor=technician, wo=wo, password=PW)
    ChecklistItem.objects.filter(work_order=wo, position=2).update(
        note="actually found a crack"
    )  # direct DB edit
    wo.refresh_from_db()
    assert services.verify_signatures(wo) is False
    with pytest.raises(DomainError) as err:
        services.certify(actor=planner, wo=wo, password=PW)
    assert err.value.code == "signature_mismatch"


def test_reject_sends_back_and_requires_new_signature(wo, technician, planner):
    complete_checklist(wo, technician)
    services.tech_sign_off(actor=technician, wo=wo, password=PW)
    services.reject(actor=planner, wo=wo, reason="photo missing")
    wo.refresh_from_db()
    assert wo.status == WorkOrder.Status.IN_PROGRESS and wo.tech_signature == ""
    services.tech_sign_off(actor=technician, wo=wo, password=PW)
    services.certify(actor=planner, wo=wo, password=PW)


def test_invalid_transitions_rejected(wo, planner, technician):
    with pytest.raises(DomainError) as err:
        services.certify(actor=planner, wo=wo, password=PW)
    assert err.value.code == "bad_transition"
    services.cancel(actor=planner, wo=wo, reason="duplicate")
    with pytest.raises(DomainError):
        services.start(actor=technician, wo=wo)


def test_grounding_work_order_grounds_aircraft(planner, aircraft):
    services.create_work_order(actor=planner, aircraft=aircraft, title="Wing skin dent", grounding=True)
    [aw] = engine.fleet_airworthiness()
    assert aw.status == engine.GROUNDED and "Wing skin dent" in aw.reasons[0]


def test_from_due_item_and_no_duplicates(planner, aircraft, rule):
    key = f"rule:{rule.pk}:aircraft:{aircraft.pk}"
    wo = services.create_from_due_item(actor=planner, key=key)
    assert wo.rule == rule and wo.checklist.count() == 3
    with pytest.raises(DomainError) as err:
        services.create_from_due_item(actor=planner, key=key)
    assert err.value.code == "duplicate"


# --- over HTTP -------------------------------------------------------------


def login(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_full_flow_over_http_with_role_checks(planner, technician, viewer, aircraft, rule):
    p, t, v = login(planner), login(technician), login(viewer)
    res = p.post(
        "/api/work-orders/from-due-item/",
        {"key": f"rule:{rule.pk}:aircraft:{aircraft.pk}", "assigned_to": technician.pk},
        format="json",
    )
    assert res.status_code == 201, res.data
    wo_id = res.data["id"]

    assert v.post(f"/api/work-orders/{wo_id}/start/").status_code == 403
    assert p.post(f"/api/work-orders/{wo_id}/start/").status_code == 403  # planners don't do tech work
    assert t.post(f"/api/work-orders/{wo_id}/start/").data["status"] == "IN_PROGRESS"

    for item in res.data["checklist"]:
        r = t.post(f"/api/work-orders/{wo_id}/checklist/", {"item": item["id"], "done": True}, format="json")
        assert r.status_code == 200
    assert r.data["progress"] == {"done": 3, "total": 3}

    assert t.post(f"/api/work-orders/{wo_id}/sign-off/", {"password": "nope"}).status_code == 400
    assert (
        t.post(f"/api/work-orders/{wo_id}/sign-off/", {"password": PW}).data["status"]
        == "AWAITING_INSPECTION"
    )
    assert t.post(f"/api/work-orders/{wo_id}/certify/", {"password": PW}).status_code == 403
    closed = p.post(f"/api/work-orders/{wo_id}/certify/", {"password": PW}).data
    assert closed["status"] == "CLOSED" and closed["inspector_signed_by"] == "planner"

    assert v.get(f"/api/work-orders/{wo_id}/verify/").data["signatures_valid"] is True
    actions = [e["action"] for e in v.get(f"/api/work-orders/{wo_id}/history/").data]
    assert actions[0] == "workorder.created" and actions[-1] == "workorder.certified"
    assert actions.count("workorder.checklist") == 3

    assert p.patch(f"/api/work-orders/{wo_id}/", {"title": "x"}, format="json").status_code == 400
    assert t.get("/api/work-orders/?mine=true").data["count"] == 1


def test_create_with_custom_checklist_over_http(planner_client, aircraft, technician):
    res = planner_client.post(
        "/api/work-orders/",
        {
            "aircraft": aircraft.pk,
            "title": "Bird strike inspection",
            "grounding": True,
            "priority": "AOG",
            "assigned_to": technician.pk,
            "checklist_items": ["Inspect leading edges", "Inspect pitot"],
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["progress"] == {"done": 0, "total": 2}
    assert res.data["number"].startswith("WO-")


def test_cannot_assign_to_non_technician(planner_client, aircraft, viewer):
    res = planner_client.post(
        "/api/work-orders/", {"aircraft": aircraft.pk, "title": "x", "assigned_to": viewer.pk}, format="json"
    )
    assert res.status_code == 400
