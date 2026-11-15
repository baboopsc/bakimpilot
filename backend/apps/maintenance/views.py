from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record

from . import engine, services
from .models import MaintenanceRecord, MaintenanceRule
from .serializers import (
    AirworthinessSerializer,
    DueItemSerializer,
    MaintenanceRecordSerializer,
    MaintenanceRuleSerializer,
)


class MaintenanceRuleViewSet(viewsets.ModelViewSet):
    queryset = MaintenanceRule.objects.select_related("part_type")
    serializer_class = MaintenanceRuleSerializer
    filterset_fields = ["applies_to", "aircraft_model", "part_type", "is_active"]
    search_fields = ["code", "name"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # deactivate, don't delete

    def perform_create(self, serializer):
        rule = serializer.save()
        record(self.request.user, "rule.created", rule, f"Created rule {rule}")

    def perform_update(self, serializer):
        rule = serializer.save()
        record(self.request.user, "rule.updated", rule, f"Updated rule {rule}", **serializer.validated_data)


class MaintenanceRecordViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Manual entry is for baselines; normally records come from closed work orders."""

    queryset = MaintenanceRecord.objects.select_related("rule", "performed_by")
    serializer_class = MaintenanceRecordSerializer
    filterset_fields = ["rule", "aircraft", "component"]

    def perform_create(self, serializer):
        serializer.instance = services.record_compliance(actor=self.request.user, **serializer.validated_data)


def _aircraft_filter(request):
    raw = request.query_params.get("aircraft")
    return [int(raw)] if raw and raw.isdigit() else None


class DueListView(APIView):
    """
    GET /api/due-items/?aircraft=<id>&status=OVERDUE,DUE_SOON
    Computed live from current counters; nothing is cached, so it's never stale.
    """

    def get(self, request):
        items = engine.compute_due_items(aircraft_ids=_aircraft_filter(request))
        wanted = request.query_params.get("status")
        if wanted:
            allowed = set(wanted.split(","))
            items = [i for i in items if i.status in allowed]
        return Response(DueItemSerializer([i.as_dict() for i in items], many=True).data)


class AirworthinessView(APIView):
    """GET /api/airworthiness/?aircraft=<id> → per-aircraft status with reasons."""

    def get(self, request):
        statuses = engine.fleet_airworthiness(aircraft_ids=_aircraft_filter(request))
        return Response(AirworthinessSerializer([s.__dict__ for s in statuses], many=True).data)
