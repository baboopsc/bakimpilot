"""
One endpoint that feeds the dashboard page: fleet readiness, a 30-day
maintenance timeline, and the counts a planner checks every morning.
"""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.models import Alert
from apps.fleet.models import Aircraft, FlightLog
from apps.inventory.models import SparePart
from apps.maintenance import engine
from apps.workorders.models import WorkOrder

TIMELINE_DAYS = 30


def readiness(statuses, active_ids) -> dict:
    """
    Readiness % = airworthy aircraft / ACTIVE aircraft. Stored aircraft are
    excluded on purpose: a parked aircraft isn't a readiness problem (D-020).
    ATTENTION counts as ready: it may fly, it just needs planning.
    """
    active = [s for s in statuses if s.aircraft_id in active_ids]
    ready = sum(s.status != engine.GROUNDED for s in active)
    by_status = defaultdict(int)
    for s in active:
        by_status[s.status] += 1
    return {
        "active_aircraft": len(active),
        "ready": ready,
        "readiness_pct": round(100 * ready / len(active), 1) if active else None,
        "by_status": {k: by_status.get(k, 0) for k in (engine.AIRWORTHY, engine.ATTENTION, engine.GROUNDED)},
    }


def timeline(items, today) -> list[dict]:
    """Due items whose projected date falls in the next 30 days (overdue ones pinned to today)."""
    horizon = today + timedelta(days=TIMELINE_DAYS)
    out = []
    for i in items:
        when = i.projected_due_date
        if i.status == engine.OVERDUE:
            when = today
        if when is None or when > horizon:
            continue
        out.append(
            {
                "date": when,
                "key": i.key,
                "title": i.title,
                "status": i.status,
                "aircraft_id": i.aircraft_id,
                "tail_number": i.tail_number,
                "kind": i.kind,
            }
        )
    return sorted(out, key=lambda x: (x["date"], x["tail_number"] or ""))


class DashboardView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        today = timezone.localdate()
        items = engine.compute_due_items(today=today)
        statuses = engine.fleet_airworthiness(today=today, items=items)
        active_ids = set(Aircraft.objects.filter(status=Aircraft.Status.ACTIVE).values_list("pk", flat=True))

        since = today - timedelta(days=TIMELINE_DAYS)
        flying = (
            FlightLog.objects.filter(takeoff_at__date__gte=since)
            .annotate(day=TruncDate("takeoff_at"))
            .values("day")
            .annotate(hours=Sum("duration_hours"), flights=Count("id"))
            .order_by("day")
        )

        return Response(
            {
                "generated_at": timezone.now(),
                "readiness": readiness(statuses, active_ids),
                "aircraft": [s.__dict__ for s in statuses],
                "due_counts": engine.counts_by_status(items),
                "timeline": timeline(items, today),
                "work_orders": dict(
                    WorkOrder.objects.exclude(
                        status__in=[WorkOrder.Status.CLOSED, WorkOrder.Status.CANCELLED]
                    )
                    .values_list("status")
                    .annotate(n=Count("id"))
                ),
                "open_alerts": dict(
                    Alert.objects.filter(resolved_at__isnull=True)
                    .values_list("severity")
                    .annotate(n=Count("id"))
                ),
                "low_stock": SparePart.objects.filter(quantity_on_hand__lte=F("min_quantity")).count(),
                "flight_hours_30d": [
                    {"day": r["day"], "hours": r["hours"], "flights": r["flights"]} for r in flying
                ],
            }
        )
