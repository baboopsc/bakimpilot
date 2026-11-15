"""
Scheduled jobs, run by Celery beat (see CELERY_BEAT_SCHEDULE in settings).

Why a schedule and not only "check when a flight is logged"? Calendar limits
expire with no event at all: a battery hits 365 days on a Sunday when nobody
logs anything. Something has to look at the clock (D-015).
"""

import logging

from celery import shared_task

from apps.maintenance import engine

from .models import Alert
from .services import Problem, sync_alerts

log = logging.getLogger(__name__)


def due_problems(items) -> list[Problem]:
    problems = []
    for item in items:
        if item.status == engine.OK:
            continue
        overdue = item.status == engine.OVERDUE
        detail = ", ".join(f"{m.remaining} {m.unit} left" for m in item.measures)
        problems.append(
            Problem(
                key=item.key,
                kind=Alert.Kind.OVERDUE if overdue else Alert.Kind.DUE_SOON,
                severity=Alert.Severity.CRITICAL if overdue else Alert.Severity.WARNING,
                title=f"{item.tail_number}: {item.title} {'OVERDUE' if overdue else 'due soon'}",
                message=detail,
                aircraft_id=item.aircraft_id,
                data={
                    "projected_due_date": str(item.projected_due_date) if item.projected_due_date else None
                },
            )
        )
    return problems


@shared_task
def run_due_check() -> dict:
    items = engine.compute_due_items()
    result = sync_alerts(due_problems(items), kinds={Alert.Kind.DUE_SOON, Alert.Kind.OVERDUE})
    log.info("due-check: %s", result)
    return result.__dict__


@shared_task
def run_stock_check() -> dict:
    from apps.inventory.services import low_stock_problems  # added in the inventory phase

    result = sync_alerts(low_stock_problems(), kinds={Alert.Kind.LOW_STOCK})
    log.info("stock-check: %s", result)
    return result.__dict__
