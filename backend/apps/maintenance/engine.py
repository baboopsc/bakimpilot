"""
The due-calculation engine (D-014).

For every (task, aircraft-or-component) pair it answers:
  * how much of each interval has been used since the task was last done?
  * is it OK, DUE_SOON, or OVERDUE?
  * on what date will it probably come due, given how much the aircraft flies?

The arithmetic (`evaluate_measure`, `build_item`) is pure: no database. That
makes the safety-critical part trivial to unit-test. `compute_due_items`
loads everything it needs in a fixed number of queries, however big the fleet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.fleet.models import Aircraft, FlightLog, Installation

from .models import MaintenanceRecord, MaintenanceRule

OK, DUE_SOON, OVERDUE = "OK", "DUE_SOON", "OVERDUE"
_SEVERITY = {OK: 0, DUE_SOON: 1, OVERDUE: 2}

HOURS, CYCLES, DAYS = "hours", "cycles", "days"
UTILIZATION_WINDOW_DAYS = 30


def worst(statuses) -> str:
    return max(statuses, key=_SEVERITY.__getitem__, default=OK)


@dataclass(frozen=True)
class Measure:
    unit: str  # hours | cycles | days
    interval: Decimal | int  # the rule interval (or hard life limit)
    used: Decimal | int  # consumed since last done (or since new)
    remaining: Decimal | int  # negative = overdue by that much
    status: str
    projected_date: date | None  # when it will be due at current utilisation


@dataclass
class DueItem:
    key: str  # stable id, used to de-duplicate alerts
    kind: str  # RULE | LIFE_LIMIT
    title: str
    aircraft_id: int | None
    tail_number: str | None
    component_id: int | None = None
    component_label: str | None = None
    rule_id: int | None = None
    last_done: date | None = None
    measures: list[Measure] = field(default_factory=list)

    @property
    def status(self) -> str:
        return worst(m.status for m in self.measures)

    @property
    def projected_due_date(self) -> date | None:
        """Whichever comes first: the earliest projected date over all measures."""
        dates = [m.projected_date for m in self.measures if m.projected_date]
        return min(dates) if dates else None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "aircraft_id": self.aircraft_id,
            "tail_number": self.tail_number,
            "component_id": self.component_id,
            "component_label": self.component_label,
            "rule_id": self.rule_id,
            "last_done": self.last_done,
            "projected_due_date": self.projected_due_date,
            "measures": [m.__dict__ for m in self.measures],
        }


@dataclass(frozen=True)
class Utilisation:
    hours_per_day: Decimal = Decimal(0)
    cycles_per_day: Decimal = Decimal(0)


# --- pure arithmetic -----------------------------------------------------


def evaluate_measure(
    unit: str,
    interval,
    used,
    *,
    today: date,
    ratio: float,
    per_day: Decimal = Decimal(0),
    due_date: date | None = None,
) -> Measure:
    """
    Classify one measure. `ratio` is the due-soon threshold, e.g. 0.9 means
    "warn once 90% of the interval is used".
    """
    remaining = interval - used
    if remaining <= 0:
        status = OVERDUE
    elif Decimal(used) >= Decimal(interval) * Decimal(str(ratio)):
        status = DUE_SOON
    else:
        status = OK

    if unit == DAYS:
        projected = due_date
    elif remaining <= 0:
        projected = today
    elif per_day > 0:
        projected = today + timedelta(days=math.ceil(Decimal(remaining) / per_day))
    else:
        projected = None  # not flying: no projection for usage-based intervals
    return Measure(unit, interval, used, remaining, status, projected)


def build_item(
    *,
    key: str,
    kind: str,
    title: str,
    today: date,
    ratio: float,
    hours_now: Decimal,
    cycles_now: int,
    since_hours: Decimal,
    since_cycles: int,
    since_date: date,
    interval_hours: Decimal | None,
    interval_cycles: int | None,
    interval_days: int | None,
    util: Utilisation,
    **ids,
) -> DueItem:
    item = DueItem(key=key, kind=kind, title=title, last_done=since_date, **ids)
    if interval_hours is not None:
        item.measures.append(
            evaluate_measure(
                HOURS,
                interval_hours,
                hours_now - since_hours,
                today=today,
                ratio=ratio,
                per_day=util.hours_per_day,
            )
        )
    if interval_cycles is not None:
        item.measures.append(
            evaluate_measure(
                CYCLES,
                interval_cycles,
                cycles_now - since_cycles,
                today=today,
                ratio=ratio,
                per_day=util.cycles_per_day,
            )
        )
    if interval_days is not None:
        due = since_date + timedelta(days=interval_days)
        item.measures.append(
            evaluate_measure(
                DAYS, interval_days, (today - since_date).days, today=today, ratio=ratio, due_date=due
            )
        )
    return item


# --- loading from the database --------------------------------------------


def utilisation(aircraft_ids, today: date) -> dict[int, Utilisation]:
    """Average flying per day over the last 30 days, per aircraft (one query)."""
    since = today - timedelta(days=UTILIZATION_WINDOW_DAYS)
    rows = (
        FlightLog.objects.filter(aircraft_id__in=aircraft_ids, takeoff_at__date__gte=since)
        .values("aircraft_id")
        .annotate(h=Sum("duration_hours"), c=Sum("cycles"))
    )
    window = Decimal(UTILIZATION_WINDOW_DAYS)
    return {r["aircraft_id"]: Utilisation(r["h"] / window, Decimal(r["c"]) / window) for r in rows}


def _latest_records():
    """Latest record per (rule, aircraft, component) via PostgreSQL DISTINCT ON (one query)."""
    rows = (
        MaintenanceRecord.objects.order_by("rule_id", "aircraft_id", "component_id", "-performed_at")
        .distinct("rule_id", "aircraft_id", "component_id")
        .values("rule_id", "aircraft_id", "component_id", "performed_at", "hours_at", "cycles_at")
    )
    return {(r["rule_id"], r["aircraft_id"], r["component_id"]): r for r in rows}


def compute_due_items(*, today: date | None = None, aircraft_ids=None) -> list[DueItem]:
    today = today or timezone.localdate()
    ratio = settings.MAINTENANCE_DUE_SOON_RATIO

    fleet = Aircraft.objects.exclude(status=Aircraft.Status.RETIRED)
    if aircraft_ids is not None:
        fleet = fleet.filter(pk__in=aircraft_ids)
    fleet = list(fleet)
    ids = [a.pk for a in fleet]

    rules = list(MaintenanceRule.objects.filter(is_active=True))
    rules_by_model: dict[str, list] = {}
    rules_by_part: dict[int, list] = {}
    for r in rules:
        if r.applies_to == MaintenanceRule.AppliesTo.AIRCRAFT_MODEL:
            rules_by_model.setdefault(r.aircraft_model, []).append(r)
        else:
            rules_by_part.setdefault(r.part_type_id, []).append(r)

    installs = Installation.objects.filter(aircraft_id__in=ids, removed_at__isnull=True).select_related(
        "component__part_type"
    )
    util = utilisation(ids, today)
    latest = _latest_records()
    items: list[DueItem] = []

    for ac in fleet:
        u = util.get(ac.pk, Utilisation())
        for rule in rules_by_model.get(ac.model, []):
            rec = latest.get((rule.pk, ac.pk, None))
            items.append(
                build_item(
                    key=f"rule:{rule.pk}:aircraft:{ac.pk}",
                    kind="RULE",
                    title=f"{rule.code} {rule.name}",
                    today=today,
                    ratio=ratio,
                    hours_now=ac.total_hours,
                    cycles_now=ac.total_cycles,
                    # Never done → measured from new / entry into service.
                    since_hours=rec["hours_at"] if rec else Decimal(0),
                    since_cycles=rec["cycles_at"] if rec else 0,
                    since_date=timezone.localtime(rec["performed_at"]).date() if rec else ac.in_service_date,
                    interval_hours=rule.interval_hours,
                    interval_cycles=rule.interval_cycles,
                    interval_days=rule.interval_days,
                    util=u,
                    aircraft_id=ac.pk,
                    tail_number=ac.tail_number,
                    rule_id=rule.pk,
                )
            )

    by_aircraft = {a.pk: a for a in fleet}
    for inst in installs:
        comp, ac = inst.component, by_aircraft[inst.aircraft_id]
        u = util.get(ac.pk, Utilisation())
        common = dict(
            today=today,
            ratio=ratio,
            hours_now=comp.hours_since_new,
            cycles_now=comp.cycles_since_new,
            util=u,
            aircraft_id=ac.pk,
            tail_number=ac.tail_number,
            component_id=comp.pk,
            component_label=f"{comp} @ {inst.position}",
        )
        pt = comp.part_type
        if pt.life_limit_hours or pt.life_limit_cycles or pt.life_limit_days:
            items.append(
                build_item(
                    key=f"life:component:{comp.pk}",
                    kind="LIFE_LIMIT",
                    title=f"Life limit {pt.part_number} S/N {comp.serial_number}",
                    since_hours=Decimal(0),
                    since_cycles=0,
                    since_date=comp.manufacture_date,
                    interval_hours=pt.life_limit_hours,
                    interval_cycles=pt.life_limit_cycles,
                    interval_days=pt.life_limit_days,
                    **common,
                )
            )
        for rule in rules_by_part.get(pt.pk, []):
            rec = latest.get((rule.pk, None, comp.pk))
            items.append(
                build_item(
                    key=f"rule:{rule.pk}:component:{comp.pk}",
                    kind="RULE",
                    title=f"{rule.code} {rule.name} — S/N {comp.serial_number}",
                    # Never done → counted from new (conservative: forces a baseline record).
                    since_hours=rec["hours_at"] if rec else Decimal(0),
                    since_cycles=rec["cycles_at"] if rec else 0,
                    since_date=timezone.localtime(rec["performed_at"]).date()
                    if rec
                    else comp.manufacture_date,
                    interval_hours=rule.interval_hours,
                    interval_cycles=rule.interval_cycles,
                    interval_days=rule.interval_days,
                    rule_id=rule.pk,
                    **common,
                )
            )

    order = {OVERDUE: 0, DUE_SOON: 1, OK: 2}
    items.sort(key=lambda i: (order[i.status], i.projected_due_date or date.max, i.key))
    return items


# --- airworthiness --------------------------------------------------------

AIRWORTHY, ATTENTION, GROUNDED = "AIRWORTHY", "ATTENTION", "GROUNDED"


@dataclass
class AirworthinessStatus:
    aircraft_id: int
    tail_number: str
    status: str
    reasons: list[str]
    overdue: int
    due_soon: int


def grounding_work_orders(aircraft_ids) -> dict[int, list[str]]:
    """Open work orders flagged as grounding, per aircraft (one query)."""
    from apps.workorders.models import WorkOrder  # local import: avoids a circular app import

    out: dict[int, list[str]] = {}
    open_grounding = WorkOrder.objects.filter(aircraft_id__in=aircraft_ids, grounding=True).exclude(
        status__in=[WorkOrder.Status.CLOSED, WorkOrder.Status.CANCELLED]
    )
    for wo in open_grounding:
        out.setdefault(wo.aircraft_id, []).append(f"Open grounding work order {wo.number}: {wo.title}")
    return out


def fleet_airworthiness(
    *, today: date | None = None, aircraft_ids=None, items=None
) -> list[AirworthinessStatus]:
    """
    GROUNDED  — any overdue task or life limit, or an open grounding work order.
    ATTENTION — airworthy, but something is due soon.
    AIRWORTHY — nothing pending.
    """
    if items is None:
        items = compute_due_items(today=today, aircraft_ids=aircraft_ids)
    fleet = Aircraft.objects.exclude(status=Aircraft.Status.RETIRED)
    if aircraft_ids is not None:
        fleet = fleet.filter(pk__in=aircraft_ids)
    fleet = list(fleet)
    grounding = grounding_work_orders([a.pk for a in fleet])

    result = []
    for ac in fleet:
        mine = [i for i in items if i.aircraft_id == ac.pk]
        overdue = [i for i in mine if i.status == OVERDUE]
        soon = [i for i in mine if i.status == DUE_SOON]
        reasons = [f"OVERDUE: {i.title}" for i in overdue] + grounding.get(ac.pk, [])
        if reasons:
            status = GROUNDED
        elif soon:
            status = ATTENTION
            reasons = [f"Due soon: {i.title}" for i in soon]
        else:
            status = AIRWORTHY
        result.append(AirworthinessStatus(ac.pk, ac.tail_number, status, reasons, len(overdue), len(soon)))
    return result


def counts_by_status(items) -> dict[str, int]:
    out = {OK: 0, DUE_SOON: 0, OVERDUE: 0}
    for i in items:
        out[i.status] += 1
    return out
