from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.fleet.models import Aircraft, Component
from config.exceptions import DomainError

from .models import MaintenanceRecord, MaintenanceRule


def _check_target(rule: MaintenanceRule, aircraft: Aircraft | None, component: Component | None) -> None:
    if (aircraft is None) == (component is None):
        raise DomainError("Give exactly one of aircraft or component.", "bad_target")
    if rule.applies_to == MaintenanceRule.AppliesTo.AIRCRAFT_MODEL:
        if aircraft is None or aircraft.model != rule.aircraft_model:
            raise DomainError(f"Rule {rule.code} applies to {rule.aircraft_model} aircraft.", "rule_mismatch")
    elif component is None or component.part_type_id != rule.part_type_id:
        raise DomainError(f"Rule {rule.code} applies to part type {rule.part_type}.", "rule_mismatch")


@transaction.atomic
def record_compliance(
    *,
    actor,
    rule: MaintenanceRule,
    aircraft: Aircraft | None = None,
    component: Component | None = None,
    performed_at: datetime | None = None,
    hours_at: Decimal | None = None,
    cycles_at: int | None = None,
    notes: str = "",
) -> MaintenanceRecord:
    """
    Record that `rule` was done. By default the current counters are snapshotted.
    Explicit `hours_at`/`cycles_at` are for baselines entered by a planner
    (e.g. "the 50 h inspection was last done at 430 h, before we had this system").
    """
    _check_target(rule, aircraft, component)
    performed_at = performed_at or timezone.now()
    if performed_at > timezone.now():
        raise DomainError("Maintenance can't be recorded in the future.", "future_record")

    target = aircraft or component
    target = type(target).objects.select_for_update().get(pk=target.pk)
    current_hours = target.total_hours if aircraft else target.hours_since_new
    current_cycles = target.total_cycles if aircraft else target.cycles_since_new
    hours_at = current_hours if hours_at is None else hours_at
    cycles_at = current_cycles if cycles_at is None else cycles_at
    if hours_at > current_hours or cycles_at > current_cycles:
        raise DomainError("Recorded counters can't exceed the current counters.", "counters_ahead")

    rec = MaintenanceRecord.objects.create(
        rule=rule,
        aircraft=aircraft,
        component=component,
        performed_at=performed_at,
        hours_at=hours_at,
        cycles_at=cycles_at,
        performed_by=actor if actor and actor.is_authenticated else None,
        notes=notes,
    )
    record(
        actor,
        "maintenance.recorded",
        rec,
        f"{rule.code} done on {target} at {hours_at} h / {cycles_at} cyc",
        rule=rule.code,
        target=str(target),
        hours_at=hours_at,
        cycles_at=cycles_at,
    )
    return rec
