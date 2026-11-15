from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.alerts.models import Alert
from apps.fleet.tests.factories import AircraftFactory
from apps.inventory import services
from apps.inventory.models import SparePart, StockMovement
from apps.workorders import services as wo_services
from config.exceptions import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def filter_part():
    return SparePart.objects.create(part_number="FLT-01", name="Fuel filter", min_quantity=Decimal(2))


@pytest.fixture
def open_wo(planner, technician):
    wo = wo_services.create_work_order(
        actor=planner, aircraft=AircraftFactory(), title="Replace filter", assigned_to=technician
    )
    wo_services.start(actor=technician, wo=wo)
    return wo


def test_receive_and_issue_keep_ledger_and_balance_in_sync(filter_part, planner, technician, open_wo):
    services.receive(actor=planner, part=filter_part, quantity=Decimal(5))
    services.issue_to_work_order(actor=technician, part=filter_part, quantity=Decimal(2), work_order=open_wo)
    filter_part.refresh_from_db()
    assert filter_part.quantity_on_hand == Decimal(3)
    moves = list(StockMovement.objects.order_by("id").values_list("delta", "balance_after", "reason"))
    assert moves == [(Decimal(5), Decimal(5), "RECEIPT"), (Decimal(-2), Decimal(3), "ISSUE")]
    assert open_wo.parts_used.count() == 1


def test_cannot_issue_more_than_on_hand(filter_part, planner, technician, open_wo):
    services.receive(actor=planner, part=filter_part, quantity=Decimal(1))
    with pytest.raises(DomainError) as err:
        services.issue_to_work_order(
            actor=technician, part=filter_part, quantity=Decimal(2), work_order=open_wo
        )
    assert err.value.code == "insufficient_stock"


def test_database_refuses_negative_stock(filter_part):
    with pytest.raises(IntegrityError):
        SparePart.objects.filter(pk=filter_part.pk).update(quantity_on_hand=Decimal(-1))


def test_only_assignee_issues_and_only_to_work_in_progress(filter_part, planner, technician, open_wo):
    services.receive(actor=planner, part=filter_part, quantity=Decimal(5))
    with pytest.raises(DomainError):
        services.issue_to_work_order(actor=planner, part=filter_part, quantity=Decimal(1), work_order=open_wo)
    wo_services.cancel(actor=planner, wo=open_wo, reason="x")
    open_wo.refresh_from_db()
    with pytest.raises(DomainError):
        services.issue_to_work_order(
            actor=technician, part=filter_part, quantity=Decimal(1), work_order=open_wo
        )


def test_adjustment_requires_note(filter_part, planner):
    with pytest.raises(DomainError):
        services.adjust(actor=planner, part=filter_part, delta=Decimal(1), note=" ")


def test_low_stock_alert_raised_on_issue_and_resolved_on_receipt(
    filter_part, planner, technician, open_wo, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        services.receive(actor=planner, part=filter_part, quantity=Decimal(3))
    assert not Alert.objects.exists()

    with django_capture_on_commit_callbacks(execute=True):
        services.issue_to_work_order(
            actor=technician, part=filter_part, quantity=Decimal(2), work_order=open_wo
        )
    alert = Alert.objects.get(kind=Alert.Kind.LOW_STOCK, resolved_at__isnull=True)
    assert "Low stock" in alert.title

    with django_capture_on_commit_callbacks(execute=True):
        services.receive(actor=planner, part=filter_part, quantity=Decimal(10))
    alert.refresh_from_db()
    assert alert.resolved_at is not None


def test_api_permissions_and_low_filter(planner_client, tech_client, viewer_client, filter_part, open_wo):
    assert (
        viewer_client.post(f"/api/spare-parts/{filter_part.pk}/receive/", {"quantity": "1"}).status_code
        == 403
    )
    res = planner_client.post(f"/api/spare-parts/{filter_part.pk}/receive/", {"quantity": "4"})
    assert res.status_code == 200 and res.data["quantity_on_hand"] == "4.00"
    # quantity can't be edited directly, only via movements
    planner_client.patch(f"/api/spare-parts/{filter_part.pk}/", {"quantity_on_hand": "999"})
    assert viewer_client.get(f"/api/spare-parts/{filter_part.pk}/").data["quantity_on_hand"] == "4.00"

    res = tech_client.post(
        f"/api/spare-parts/{filter_part.pk}/issue/", {"quantity": "3", "work_order": open_wo.pk}
    )
    assert res.status_code == 200 and res.data["is_low"] is True
    assert viewer_client.get("/api/spare-parts/?low=true").data["count"] == 1
    assert viewer_client.get(f"/api/stock-movements/?work_order={open_wo.pk}").data["count"] == 1
