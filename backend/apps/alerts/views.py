from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Role

from .models import Alert
from .tasks import run_due_check


class AlertSerializer(serializers.ModelSerializer):
    tail_number = serializers.CharField(source="aircraft.tail_number", read_only=True, default=None)
    acknowledged_by = serializers.CharField(source="acknowledged_by.username", read_only=True, default=None)

    class Meta:
        model = Alert
        fields = [
            "id",
            "kind",
            "severity",
            "title",
            "message",
            "aircraft",
            "tail_number",
            "data",
            "created_at",
            "resolved_at",
            "acknowledged_at",
            "acknowledged_by",
        ]
        read_only_fields = fields


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Alert.objects.select_related("aircraft", "acknowledged_by")
    serializer_class = AlertSerializer
    filterset_fields = {
        "kind": ["exact"],
        "severity": ["exact"],
        "aircraft": ["exact"],
        "resolved_at": ["isnull"],
    }
    action_roles = {
        "acknowledge": {Role.ADMIN, Role.PLANNER, Role.TECHNICIAN},
        "run_check": {Role.ADMIN, Role.PLANNER},
    }

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        """'I've seen this.' Doesn't resolve it: only fixing the problem does."""
        alert = self.get_object()
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = request.user
        alert.save(update_fields=["acknowledged_at", "acknowledged_by"])
        return Response(AlertSerializer(alert).data)

    @action(detail=False, methods=["post"], url_path="run-check")
    def run_check(self, request):
        """Run the due-check now instead of waiting for the hourly schedule."""
        return Response(run_due_check())
