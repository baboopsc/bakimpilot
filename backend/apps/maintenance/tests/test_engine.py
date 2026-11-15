from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.fleet import services as fleet
from apps.fleet.tests.factories import AircraftFactory, ComponentFactory, PartTypeFactory
from apps.maintenance import engine
from apps.maintenance.models import MaintenanceRule
from apps.maintenance.services import record_compliance
from config.exceptions import DomainError

TZ = ZoneInfo("Europe/Istanbul")


# --- pure arithmetic: no database ----------------------------------------


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        (0, engine.OK),
        (44, engine.OK),
        (45, engine.DUE_SOON),
        (49.99, engine.DUE_SOON),
        (50, engine.OVERDUE),
        (61, engine.OVERDUE),
    ],
)
def test_measure_thresholds_at_90_percent(used, expected):
    m = engine.evaluate_measure("hours", Decimal(50), Decimal(str(used)), today=date(2026, 3, 1), ratio=0.9)
    assert m.status == expected


def test_projection_uses_daily_utilisation():
    m = engine.evaluate_measure(
        "hours", Decimal(50), Decimal(30), today=date(2026, 3, 1), ratio=0.9, per_day=Decimal("2.5")
    )
    assert m.remaining == 20
    assert m.projected_date == date(2026, 3, 9)  # 20 h / 2.5 h per day = 8 days


def test_no_projection_when_aircraft_is_not_flying():
    m = engine.evaluate_measure("cycles", 100, 10, today=date(2026, 3, 1), ratio=0.9)
    assert m.projected_date is None


def test_whichever_comes_first():
    item = engine.build_item(
        key="k",
        kind="RULE",
        title="t",
        today=date(2026, 3, 1),
        ratio=0.9,
        hours_now=Decimal(10),
        cycles_now=5,
        since_hours=Decimal(0),
        since_cycles=0,
        since_date=date(2025, 3, 10),
        interval_hours=Decimal(100),  # 10% used: OK
        interval_cycles=500,  # 1% used: OK
        interval_days=365,  # 356 of 365 days used: DUE_SOON
        util=engine.Utilisation(),
        aircraft_id=1,
        tail_number="T",
    )
    assert item.status == engine.DUE_SOON
    assert item.projected_due_date == date(2026, 3, 10)


# --- with the database -----------------------------------------------------


def at(days_ago: int, hour: int = 8) -> datetime:
    d = timezone.localdate() - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, hour, tzinfo=TZ)


def fly(aircraft, days_ago, hours):
    start = at(days_ago)
    return fleet.log_flight(
        actor=None, aircraft=aircraft, takeoff_at=start, landing_at=start + timedelta(hours=hours)
    )


@pytest.fixture
def tb2():
    return AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=100))


@pytest.fixture
def rule_50h(db):
    return MaintenanceRule.objects.create(
        code="TB2-50H",
        name="50 h inspection",
        applies_to="AIRCRAFT_MODEL",
        aircraft_model="TB2",
        interval_hours=50,
    )


def _item(key_prefix):
    return next(i for i in engine.compute_due_items() if i.key.startswith(key_prefix))


@pytest.mark.django_db
def test_aircraft_rule_goes_ok_due_soon_overdue_and_resets_after_compliance(tb2, rule_50h, planner):
    fly(tb2, 12, 20)
    fly(tb2, 11, 20)  # 40 h
    assert _item(f"rule:{rule_50h.pk}:aircraft:{tb2.pk}").status == engine.OK
    fly(tb2, 10, 6)  # 46 h
    assert _item("rule:").status == engine.DUE_SOON
    fly(tb2, 9, 5)  # 51 h
    item = _item("rule:")
    assert item.status == engine.OVERDUE
    assert item.measures[0].remaining == Decimal("-1.00")
    [aw] = engine.fleet_airworthiness()
    assert aw.status == engine.GROUNDED and "OVERDUE" in aw.reasons[0]

    tb2.refresh_from_db()
    record_compliance(actor=planner, rule=rule_50h, aircraft=tb2)
    item = _item("rule:")
    assert item.status == engine.OK and item.measures[0].used == 0
    assert engine.fleet_airworthiness()[0].status == engine.AIRWORTHY


@pytest.mark.django_db
def test_rules_only_apply_to_matching_aircraft_model(rule_50h):
    AircraftFactory(model="AKINCI")
    assert engine.compute_due_items() == []


@pytest.mark.django_db
def test_component_rule_follows_component_to_another_aircraft(planner):
    pt = PartTypeFactory(life_limit_hours=None, life_limit_cycles=None)
    rule = MaintenanceRule.objects.create(
        code="ENG-25H", name="Engine borescope", applies_to="PART_TYPE", part_type=pt, interval_hours=25
    )
    a, b = AircraftFactory(), AircraftFactory()
    eng = ComponentFactory(part_type=pt)
    fleet.install_component(actor=None, component=eng, aircraft=a, position="ENGINE", at=at(20))
    fly(a, 19, 20)
    fleet.remove_component(actor=None, component=eng, reason="swap", at=at(18))
    fleet.install_component(actor=None, component=eng, aircraft=b, position="ENGINE", at=at(17))
    fly(b, 16, 3)  # engine has 23 of 25 h

    item = _item(f"rule:{rule.pk}:component:{eng.pk}")
    assert item.tail_number == b.tail_number
    assert item.status == engine.DUE_SOON
    assert item.measures[0].used == Decimal("23.00")


@pytest.mark.django_db
def test_life_limited_part_grounds_its_aircraft():
    ac = AircraftFactory()
    pt = PartTypeFactory(life_limit_hours=Decimal(10), life_limit_cycles=None)
    eng = ComponentFactory(part_type=pt)
    fleet.install_component(actor=None, component=eng, aircraft=ac, position="ENGINE", at=at(5))
    fly(ac, 4, 11)
    item = _item("life:")
    assert item.kind == "LIFE_LIMIT" and item.status == engine.OVERDUE
    assert engine.fleet_airworthiness()[0].status == engine.GROUNDED


@pytest.mark.django_db
def test_calendar_rule_counts_from_in_service_date_then_from_last_record(planner):
    ac = AircraftFactory(model="TB2", in_service_date=timezone.localdate() - timedelta(days=95))
    rule = MaintenanceRule.objects.create(
        code="TB2-90D",
        name="90 day check",
        applies_to="AIRCRAFT_MODEL",
        aircraft_model="TB2",
        interval_days=90,
    )
    assert _item("rule:").status == engine.OVERDUE
    record_compliance(actor=planner, rule=rule, aircraft=ac, performed_at=at(1))
    item = _item("rule:")
    assert item.status == engine.OK
    assert item.projected_due_date == timezone.localdate() + timedelta(days=89)


@pytest.mark.django_db
def test_projected_due_date_from_recent_utilisation(tb2, rule_50h):
    for d in range(1, 11):
        fly(tb2, d, 3)  # 30 h in last 10 days → 1 h/day averaged over 30 days
    item = _item("rule:")
    assert item.projected_due_date == timezone.localdate() + timedelta(days=20)


@pytest.mark.django_db
def test_compliance_rejects_wrong_target_and_future_and_ahead_counters(tb2, rule_50h, planner):
    other = AircraftFactory(model="AKINCI")
    with pytest.raises(DomainError, match="applies to"):
        record_compliance(actor=planner, rule=rule_50h, aircraft=other)
    with pytest.raises(DomainError):
        record_compliance(
            actor=planner, rule=rule_50h, aircraft=tb2, performed_at=timezone.now() + timedelta(days=1)
        )
    with pytest.raises(DomainError):
        record_compliance(actor=planner, rule=rule_50h, aircraft=tb2, hours_at=Decimal(999))


@pytest.mark.django_db
def test_query_count_does_not_grow_with_fleet_size(django_assert_max_num_queries, rule_50h):
    for _ in range(15):
        ac = AircraftFactory(model="TB2")
        fleet.install_component(
            actor=None, component=ComponentFactory(), aircraft=ac, position="ENGINE", at=at(3)
        )
    with django_assert_max_num_queries(5):
        items = engine.compute_due_items()
    assert len(items) == 30  # 15 aircraft rules + 15 life limits
