"""
Fleet business rules (D-007). Every function that changes data:
  1. runs inside one DB transaction (all-or-nothing),
  2. locks the rows it reads-then-writes (SELECT ... FOR UPDATE) so two
     simultaneous requests can't both pass a check and both write,
  3. writes an audit entry in the same transaction.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.audit.services import record
from config.exceptions import DomainError

from .models import ZERO, Aircraft, Component, FlightLog, Installation

TWO_PLACES = Decimal("0.01")


def hours_between(start: datetime, end: datetime) -> Decimal:
    seconds = Decimal((end - start).total_seconds())
    return (seconds / Decimal(3600)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# --- life limits ---------------------------------------------------------


@dataclass(frozen=True)
class LifeRemaining:
    hours: Decimal | None
    cycles: int | None
    days: int | None

    @property
    def expired(self) -> bool:
        return any(v is not None and v <= 0 for v in (self.hours, self.cycles, self.days))


def life_remaining(component: Component, today: date | None = None) -> LifeRemaining:
    """How much hard life is left, per measure. None = no limit of that kind."""
    today = today or timezone.localdate()
    pt = component.part_type
    return LifeRemaining(
        hours=None if pt.life_limit_hours is None else pt.life_limit_hours - component.hours_since_new,
        cycles=None if pt.life_limit_cycles is None else pt.life_limit_cycles - component.cycles_since_new,
        days=None
        if pt.life_limit_days is None
        else pt.life_limit_days - (today - component.manufacture_date).days,
    )


# --- components ----------------------------------------------------------


@transaction.atomic
def create_aircraft(*, actor, **fields) -> Aircraft:
    aircraft = Aircraft(**fields)
    aircraft.total_hours = aircraft.initial_hours
    aircraft.total_cycles = aircraft.initial_cycles
    aircraft.full_clean()
    aircraft.save()
    record(actor, "aircraft.created", aircraft, f"Registered aircraft {aircraft}")
    return aircraft


@transaction.atomic
def create_component(*, actor, **fields) -> Component:
    component = Component(**fields)
    # Usage since new starts at whatever the part already had when we received it.
    component.hours_since_new = component.initial_hours
    component.cycles_since_new = component.initial_cycles
    component.full_clean()
    component.save()
    record(actor, "component.created", component, f"Registered {component}")
    return component


@transaction.atomic
def install_component(
    *, actor, component: Component, aircraft: Aircraft, position: str, at: datetime | None = None
) -> Installation:
    at = at or timezone.now()
    # Lock both rows: blocks a concurrent install of the same part, and a
    # concurrent flight changing the aircraft totals we snapshot below.
    component = Component.objects.select_for_update().select_related("part_type").get(pk=component.pk)
    aircraft = Aircraft.objects.select_for_update().get(pk=aircraft.pk)

    if aircraft.status == Aircraft.Status.RETIRED:
        raise DomainError("Cannot install parts on a retired aircraft.", "aircraft_retired")
    if component.status != Component.Status.SERVICEABLE:
        raise DomainError(
            f"{component} is {component.status.lower()} and cannot be installed.", "not_serviceable"
        )
    if life_remaining(component, at.date()).expired:
        raise DomainError(f"{component} has reached its life limit.", "life_expired")
    if component.installations.filter(removed_at__isnull=True).exists():
        raise DomainError(f"{component} is already installed on another aircraft.", "already_installed")
    if Installation.objects.filter(aircraft=aircraft, position=position, removed_at__isnull=True).exists():
        raise DomainError(f"Position {position} on {aircraft} is occupied.", "position_occupied")
    last = component.installations.order_by("-removed_at").first()
    if last and last.removed_at and at < last.removed_at:
        raise DomainError("Install time is before the component's last removal.", "time_order")

    installation = Installation.objects.create(
        component=component,
        aircraft=aircraft,
        position=position,
        installed_at=at,
        aircraft_hours_at_install=aircraft.total_hours,
        aircraft_cycles_at_install=aircraft.total_cycles,
        component_hours_at_install=component.hours_since_new,
        component_cycles_at_install=component.cycles_since_new,
    )
    record(
        actor,
        "component.installed",
        component,
        f"Installed {component} on {aircraft} at {position}",
        aircraft=aircraft.tail_number,
        position=position,
        at=at,
    )
    return installation


@transaction.atomic
def remove_component(
    *,
    actor,
    component: Component,
    reason: str,
    at: datetime | None = None,
    mark_unserviceable: bool = False,
) -> Installation:
    at = at or timezone.now()
    component = Component.objects.select_for_update().get(pk=component.pk)
    installation = component.installations.select_for_update().filter(removed_at__isnull=True).first()
    if installation is None:
        raise DomainError(f"{component} is not installed.", "not_installed")
    if at < installation.installed_at:
        raise DomainError("Removal time is before install time.", "time_order")

    installation.removed_at = at
    installation.removal_reason = reason
    installation.save(update_fields=["removed_at", "removal_reason"])
    if mark_unserviceable:
        component.status = Component.Status.UNSERVICEABLE
        component.save(update_fields=["status"])
    record(
        actor,
        "component.removed",
        component,
        f"Removed {component} from {installation.aircraft}: {reason}",
        aircraft=installation.aircraft.tail_number,
        reason=reason,
        unserviceable=mark_unserviceable,
    )
    return installation


# --- flights -------------------------------------------------------------


def installed_at_time(aircraft: Aircraft, moment: datetime):
    """Installations that were on `aircraft` at `moment` (supports back-dated flights)."""
    return Installation.objects.filter(aircraft=aircraft, installed_at__lte=moment).filter(
        Q(removed_at__isnull=True) | Q(removed_at__gt=moment)
    )


@transaction.atomic
def log_flight(
    *,
    actor,
    aircraft: Aircraft,
    takeoff_at: datetime,
    landing_at: datetime,
    cycles: int = 1,
    **extra,
) -> FlightLog:
    if landing_at <= takeoff_at:
        raise DomainError("Landing must be after take-off.", "time_order")
    if landing_at > timezone.now() + timedelta(minutes=5):
        raise DomainError("Cannot log a flight that has not happened yet.", "future_flight")
    if cycles < 1:
        raise DomainError("A flight has at least one cycle.", "invalid_cycles")

    # One lock per aircraft serialises all counter updates for it (D-011).
    aircraft = Aircraft.objects.select_for_update().get(pk=aircraft.pk)
    if aircraft.status != Aircraft.Status.ACTIVE:
        raise DomainError(
            f"{aircraft} is {aircraft.status.lower()}; flights can't be logged.", "aircraft_inactive"
        )
    overlapping = FlightLog.objects.filter(
        aircraft=aircraft, takeoff_at__lt=landing_at, landing_at__gt=takeoff_at
    )
    if overlapping.exists():
        raise DomainError("This flight overlaps another flight of the same aircraft.", "overlap")

    hours = hours_between(takeoff_at, landing_at)
    flight = FlightLog.objects.create(
        aircraft=aircraft,
        takeoff_at=takeoff_at,
        landing_at=landing_at,
        cycles=cycles,
        duration_hours=hours,
        logged_by=actor if actor and actor.is_authenticated else None,
        **extra,
    )

    # F() expressions make the database do "x = x + n" atomically, instead of
    # read-modify-write in Python which can lose updates.
    Aircraft.objects.filter(pk=aircraft.pk).update(
        total_hours=F("total_hours") + hours, total_cycles=F("total_cycles") + cycles
    )
    component_ids = list(installed_at_time(aircraft, takeoff_at).values_list("component_id", flat=True))
    Component.objects.filter(pk__in=component_ids).update(
        hours_since_new=F("hours_since_new") + hours, cycles_since_new=F("cycles_since_new") + cycles
    )
    record(
        actor,
        "flight.logged",
        flight,
        f"{aircraft} flew {hours} h / {cycles} cyc",
        aircraft=aircraft.tail_number,
        hours=hours,
        cycles=cycles,
        components=component_ids,
    )
    return flight


# --- consistency check ---------------------------------------------------


def expected_component_usage(component: Component) -> tuple[Decimal, int]:
    """
    Rebuild a component's usage from first principles: initial usage plus every
    flight flown by whichever aircraft it was on at the time. Used to verify the
    running totals (management command `verify_counters`, and tests).
    """
    hours, cycles = component.initial_hours, component.initial_cycles
    for inst in component.installations.all():
        flights = FlightLog.objects.filter(aircraft=inst.aircraft, takeoff_at__gte=inst.installed_at)
        if inst.removed_at:
            flights = flights.filter(takeoff_at__lt=inst.removed_at)
        agg = flights.aggregate(h=Sum("duration_hours"), c=Sum("cycles"))
        hours += agg["h"] or ZERO
        cycles += agg["c"] or 0
    return hours, cycles


def expected_aircraft_usage(aircraft: Aircraft) -> tuple[Decimal, int]:
    agg = aircraft.flights.aggregate(h=Sum("duration_hours"), c=Sum("cycles"))
    return aircraft.initial_hours + (agg["h"] or ZERO), aircraft.initial_cycles + (agg["c"] or 0)
