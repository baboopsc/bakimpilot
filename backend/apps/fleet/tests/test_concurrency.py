"""
Proves the row lock in services.log_flight works under real concurrency.

Uses real threads and real transactions (transaction=True), so each thread has
its own DB connection exactly like two web requests would.
"""

import threading
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection

from apps.fleet import services
from config.exceptions import DomainError

from .factories import AircraftFactory, ComponentFactory

TZ = ZoneInfo("Europe/Istanbul")


def _run_in_parallel(fn, n):
    barrier = threading.Barrier(n)
    results = []

    def worker(i):
        try:
            barrier.wait()  # start all threads at the same instant
            results.append(fn(i))
        except Exception as exc:  # noqa: BLE001 - we want to collect every outcome
            results.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return results


@pytest.mark.django_db(transaction=True)
def test_parallel_flights_do_not_lose_updates():
    aircraft = AircraftFactory()
    engine = ComponentFactory()
    services.install_component(
        actor=None, component=engine, aircraft=aircraft, position="ENGINE", at=datetime(2026, 1, 1, tzinfo=TZ)
    )

    def log(i):
        start = datetime(2026, 2, 1, tzinfo=TZ) + timedelta(days=i)  # 8 non-overlapping flights
        return services.log_flight(
            actor=None, aircraft=aircraft, takeoff_at=start, landing_at=start + timedelta(hours=1)
        )

    results = _run_in_parallel(log, 8)

    assert not [r for r in results if isinstance(r, Exception)]
    engine.refresh_from_db()
    aircraft.refresh_from_db()
    assert aircraft.total_hours == Decimal("8.00")
    assert engine.hours_since_new == Decimal("8.00")


@pytest.mark.django_db(transaction=True)
def test_parallel_overlapping_flights_only_one_wins():
    aircraft = AircraftFactory()
    start = datetime(2026, 2, 1, 8, tzinfo=TZ)

    def log(i):
        return services.log_flight(
            actor=None, aircraft=aircraft, takeoff_at=start, landing_at=start + timedelta(hours=1 + i)
        )

    results = _run_in_parallel(log, 4)

    errors = [r for r in results if isinstance(r, DomainError)]
    assert len(errors) == 3 and all(e.code == "overlap" for e in errors)
    assert aircraft.flights.count() == 1
