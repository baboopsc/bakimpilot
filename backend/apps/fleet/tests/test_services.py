from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import IntegrityError

from apps.audit.models import AuditLog
from apps.fleet import services
from apps.fleet.models import Aircraft, Component, Installation
from config.exceptions import DomainError

from .factories import AircraftFactory, ComponentFactory, PartTypeFactory

pytestmark = pytest.mark.django_db
TZ = ZoneInfo("Europe/Istanbul")


def t(day, hour=0, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=TZ)


def fly(aircraft, day, hours=2, cycles=1, actor=None, start_hour=8):
    takeoff = t(day, start_hour)
    return services.log_flight(
        actor=actor,
        aircraft=aircraft,
        takeoff_at=takeoff,
        landing_at=takeoff + timedelta(hours=hours),
        cycles=cycles,
    )


@pytest.fixture
def aircraft():
    return AircraftFactory()


@pytest.fixture
def engine():
    return ComponentFactory()


def test_hours_between_rounds_to_hundredths():
    assert services.hours_between(t(1, 8), t(1, 9, 20)) == Decimal("1.33")


def test_flight_adds_hours_and_cycles_to_aircraft_and_installed_components(aircraft, engine, planner):
    services.install_component(actor=planner, component=engine, aircraft=aircraft, position="ENGINE", at=t(1))
    spare = ComponentFactory()  # in the store room, not installed

    fly(aircraft, 2, hours=3, cycles=2, actor=planner)

    aircraft.refresh_from_db(), engine.refresh_from_db(), spare.refresh_from_db()
    assert (aircraft.total_hours, aircraft.total_cycles) == (Decimal("3.00"), 2)
    assert (engine.hours_since_new, engine.cycles_since_new) == (Decimal("3.00"), 2)
    assert (spare.hours_since_new, spare.cycles_since_new) == (Decimal("0.00"), 0)
    assert AuditLog.objects.filter(action="flight.logged").count() == 1


def test_component_moved_between_aircraft_only_counts_flights_while_installed(engine, planner):
    a, b = AircraftFactory(), AircraftFactory()
    services.install_component(actor=planner, component=engine, aircraft=a, position="ENGINE", at=t(1))
    fly(a, 2, hours=2)
    services.remove_component(actor=planner, component=engine, reason="swap", at=t(3))
    fly(a, 4, hours=5)  # engine is not on A anymore
    services.install_component(actor=planner, component=engine, aircraft=b, position="ENGINE", at=t(5))
    fly(b, 6, hours=1)

    engine.refresh_from_db()
    assert engine.hours_since_new == Decimal("3.00")
    assert engine.cycles_since_new == 2
    assert services.expected_component_usage(engine) == (Decimal("3.00"), 2)


def test_backdated_flight_credits_components_installed_at_that_time(aircraft, planner):
    old = ComponentFactory()
    new = ComponentFactory(part_type=old.part_type)
    services.install_component(actor=planner, component=old, aircraft=aircraft, position="ENGINE", at=t(1))
    services.remove_component(actor=planner, component=old, reason="swap", at=t(10))
    services.install_component(actor=planner, component=new, aircraft=aircraft, position="ENGINE", at=t(10))

    fly(aircraft, 5, hours=4)  # entered late, but flown on day 5 with the OLD engine

    old.refresh_from_db(), new.refresh_from_db()
    assert old.hours_since_new == Decimal("4.00")
    assert new.hours_since_new == Decimal("0.00")


def test_component_initial_usage_is_included(aircraft, planner):
    pt = PartTypeFactory()
    used = services.create_component(
        actor=planner,
        part_type=pt,
        serial_number="USED-1",
        manufacture_date=date(2020, 1, 1),
        initial_hours=Decimal("120.5"),
        initial_cycles=40,
    )
    services.install_component(actor=planner, component=used, aircraft=aircraft, position="ENGINE", at=t(1))
    fly(aircraft, 2, hours=1)
    used.refresh_from_db()
    assert used.hours_since_new == Decimal("121.50")
    assert services.expected_component_usage(used) == (Decimal("121.50"), 41)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"landing_offset": timedelta(hours=-1)}, "time_order"),
        ({"cycles": 0}, "invalid_cycles"),
    ],
)
def test_invalid_flights_are_rejected(aircraft, kwargs, code):
    takeoff = t(2, 8)
    with pytest.raises(DomainError) as err:
        services.log_flight(
            actor=None,
            aircraft=aircraft,
            takeoff_at=takeoff,
            landing_at=takeoff + kwargs.get("landing_offset", timedelta(hours=1)),
            cycles=kwargs.get("cycles", 1),
        )
    assert err.value.code == code


def test_future_flight_rejected(aircraft):
    from django.utils import timezone

    start = timezone.now() + timedelta(days=1)
    with pytest.raises(DomainError, match="not happened"):
        services.log_flight(
            actor=None, aircraft=aircraft, takeoff_at=start, landing_at=start + timedelta(hours=1)
        )


def test_overlapping_flights_rejected(aircraft):
    fly(aircraft, 2, hours=3, start_hour=8)  # 08:00-11:00
    with pytest.raises(DomainError) as err:
        fly(aircraft, 2, hours=1, start_hour=10)  # 10:00-11:00
    assert err.value.code == "overlap"


def test_flights_on_stored_aircraft_rejected():
    stored = AircraftFactory(status=Aircraft.Status.STORED)
    with pytest.raises(DomainError):
        fly(stored, 2)


def test_cannot_install_component_twice(engine, planner):
    a, b = AircraftFactory(), AircraftFactory()
    services.install_component(actor=planner, component=engine, aircraft=a, position="ENGINE", at=t(1))
    with pytest.raises(DomainError) as err:
        services.install_component(actor=planner, component=engine, aircraft=b, position="ENGINE", at=t(2))
    assert err.value.code == "already_installed"


def test_cannot_fill_occupied_position(aircraft, planner):
    services.install_component(
        actor=planner, component=ComponentFactory(), aircraft=aircraft, position="ENGINE", at=t(1)
    )
    with pytest.raises(DomainError) as err:
        services.install_component(
            actor=planner, component=ComponentFactory(), aircraft=aircraft, position="ENGINE", at=t(2)
        )
    assert err.value.code == "position_occupied"


def test_database_constraint_backs_up_the_service_check(aircraft, engine):
    """Even code that skips the service can't create two open installations."""
    common = dict(
        aircraft_hours_at_install=0,
        aircraft_cycles_at_install=0,
        component_hours_at_install=0,
        component_cycles_at_install=0,
    )
    Installation.objects.create(
        component=engine, aircraft=aircraft, position="A", installed_at=t(1), **common
    )
    with pytest.raises(IntegrityError):
        Installation.objects.create(
            component=engine, aircraft=AircraftFactory(), position="B", installed_at=t(2), **common
        )


def test_life_expired_component_cannot_be_installed(aircraft, planner):
    worn = ComponentFactory(
        part_type=PartTypeFactory(life_limit_hours=Decimal("100")), hours_since_new=Decimal("100")
    )
    with pytest.raises(DomainError) as err:
        services.install_component(
            actor=planner, component=worn, aircraft=aircraft, position="ENGINE", at=t(1)
        )
    assert err.value.code == "life_expired"


def test_calendar_life_counts_from_manufacture_date():
    battery = ComponentFactory(
        part_type=PartTypeFactory(life_limit_hours=None, life_limit_cycles=None, life_limit_days=365),
        manufacture_date=date(2026, 1, 1),
    )
    assert services.life_remaining(battery, date(2026, 12, 1)).days == 31  # 365 - 334 days elapsed
    assert services.life_remaining(battery, date(2027, 1, 1)).expired
    assert services.life_remaining(battery).hours is None


def test_unserviceable_component_cannot_be_installed(aircraft, engine, planner):
    services.install_component(actor=planner, component=engine, aircraft=aircraft, position="ENGINE", at=t(1))
    services.remove_component(
        actor=planner, component=engine, reason="oil leak", at=t(2), mark_unserviceable=True
    )
    engine.refresh_from_db()
    assert engine.status == Component.Status.UNSERVICEABLE
    with pytest.raises(DomainError):
        services.install_component(
            actor=planner, component=engine, aircraft=aircraft, position="ENGINE", at=t(3)
        )


def test_removal_before_install_rejected(aircraft, engine, planner):
    services.install_component(actor=planner, component=engine, aircraft=aircraft, position="ENGINE", at=t(5))
    with pytest.raises(DomainError):
        services.remove_component(actor=planner, component=engine, reason="x", at=t(4))


def test_verify_counters_command_detects_drift(aircraft, engine, planner):
    services.install_component(actor=planner, component=engine, aircraft=aircraft, position="ENGINE", at=t(1))
    fly(aircraft, 2)
    call_command("verify_counters")  # all good

    Component.objects.filter(pk=engine.pk).update(hours_since_new=Decimal("999"))
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("verify_counters")
