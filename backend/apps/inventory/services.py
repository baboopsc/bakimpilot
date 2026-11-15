import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from apps.accounts.models import User
from apps.alerts.models import Alert
from apps.alerts.services import Problem
from apps.audit.services import record
from apps.workorders.models import WorkOrder
from config.exceptions import DomainError

from .models import SparePart, StockMovement

log = logging.getLogger(__name__)


def _move(
    *, actor, part: SparePart, delta: Decimal, reason: str, note: str = "", work_order=None
) -> StockMovement:
    if delta == 0:
        raise DomainError("Quantity must not be zero.", "zero_quantity")
    part = SparePart.objects.select_for_update().get(pk=part.pk)
    new_balance = part.quantity_on_hand + delta
    if new_balance < 0:
        raise DomainError(
            f"Only {part.quantity_on_hand} {part.unit} of {part.part_number} in stock.", "insufficient_stock"
        )
    SparePart.objects.filter(pk=part.pk).update(quantity_on_hand=F("quantity_on_hand") + delta)
    movement = StockMovement.objects.create(
        part=part,
        delta=delta,
        balance_after=new_balance,
        reason=reason,
        work_order=work_order,
        note=note,
        actor=actor if actor and actor.is_authenticated else None,
    )
    record(
        actor,
        f"stock.{reason.lower()}",
        part,
        f"{part.part_number} {delta:+} {part.unit} → {new_balance}",
        delta=delta,
        balance=new_balance,
        work_order=work_order.number if work_order else None,
    )
    if new_balance <= part.min_quantity or part.quantity_on_hand <= part.min_quantity:
        # Crossed (or still under) the reorder point: refresh low-stock alerts
        # right after commit instead of waiting for the daily check.
        transaction.on_commit(_queue_stock_check)
    return movement


def _queue_stock_check() -> None:
    from apps.alerts.tasks import run_stock_check

    try:
        run_stock_check.delay()
    except Exception:  # broker down: the stock change itself already succeeded
        log.warning("Could not queue stock check; the daily schedule will catch up.", exc_info=True)


@transaction.atomic
def receive(*, actor: User, part: SparePart, quantity: Decimal, note: str = "") -> StockMovement:
    if quantity <= 0:
        raise DomainError("Received quantity must be positive.", "bad_quantity")
    return _move(actor=actor, part=part, delta=quantity, reason=StockMovement.Reason.RECEIPT, note=note)


@transaction.atomic
def adjust(*, actor: User, part: SparePart, delta: Decimal, note: str) -> StockMovement:
    if not note.strip():
        raise DomainError("Adjustments need a note explaining why.", "note_required")
    return _move(actor=actor, part=part, delta=delta, reason=StockMovement.Reason.ADJUSTMENT, note=note)


@transaction.atomic
def issue_to_work_order(
    *, actor: User, part: SparePart, quantity: Decimal, work_order: WorkOrder
) -> StockMovement:
    if quantity <= 0:
        raise DomainError("Issued quantity must be positive.", "bad_quantity")
    # Re-read and lock: never trust a status from an object that may be stale.
    work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
    if work_order.status != WorkOrder.Status.IN_PROGRESS:
        raise DomainError("Parts can only be issued to work orders in progress.", "bad_transition")
    if work_order.assigned_to_id != actor.pk:
        raise DomainError("Only the assigned technician can draw parts for this work order.", "not_assignee")
    return _move(
        actor=actor,
        part=part,
        delta=-quantity,
        reason=StockMovement.Reason.ISSUE,
        work_order=work_order,
        note=f"For {work_order.number}",
    )


def low_stock_problems() -> list[Problem]:
    problems = []
    for part in SparePart.objects.filter(quantity_on_hand__lte=F("min_quantity")):
        empty = part.quantity_on_hand == 0
        problems.append(
            Problem(
                key=f"stock:{part.pk}",
                kind=Alert.Kind.LOW_STOCK,
                severity=Alert.Severity.CRITICAL if empty else Alert.Severity.WARNING,
                title=f"{'Out of stock' if empty else 'Low stock'}: {part.part_number} {part.name}",
                message=f"{part.quantity_on_hand} {part.unit} on hand, reorder point {part.min_quantity}",
                data={"part_id": part.pk},
            )
        )
    return problems
