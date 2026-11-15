"""
Reconcile alerts with reality: open alerts for current problems, resolve
alerts whose problem has gone away. Running it twice changes nothing the
second time (idempotent), so it's safe to retry or run on a schedule.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Alert


@dataclass(frozen=True)
class Problem:
    key: str
    kind: str
    severity: str
    title: str
    message: str = ""
    aircraft_id: int | None = None
    data: dict | None = None


@dataclass(frozen=True)
class SyncResult:
    opened: int
    updated: int
    resolved: int


@transaction.atomic
def sync_alerts(problems: list[Problem], *, kinds: set[str]) -> SyncResult:
    """
    `kinds` scopes the reconciliation: a due-check only resolves DUE_SOON/OVERDUE
    alerts, never LOW_STOCK ones it knows nothing about.
    """
    now = timezone.now()
    open_alerts = {
        a.dedup_key: a
        for a in Alert.objects.select_for_update().filter(kind__in=kinds, resolved_at__isnull=True)
    }
    wanted = {p.key: p for p in problems}
    opened = updated = resolved = 0

    for key, alert in open_alerts.items():
        if key not in wanted:
            alert.resolved_at = now
            alert.save(update_fields=["resolved_at"])
            resolved += 1

    for key, p in wanted.items():
        existing = open_alerts.get(key)
        if existing is None:
            Alert.objects.create(
                kind=p.kind,
                severity=p.severity,
                title=p.title,
                message=p.message,
                dedup_key=key,
                aircraft_id=p.aircraft_id,
                data=p.data or {},
            )
            opened += 1
        elif existing.kind != p.kind or existing.severity != p.severity:
            # Escalation (DUE_SOON → OVERDUE): re-raise so it's noticed again.
            existing.kind, existing.severity, existing.title, existing.message = (
                p.kind,
                p.severity,
                p.title,
                p.message,
            )
            existing.data = p.data or {}
            existing.created_at = now
            existing.acknowledged_at = existing.acknowledged_by = None
            existing.save()
            updated += 1
    return SyncResult(opened, updated, resolved)
