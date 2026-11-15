from rest_framework import serializers, viewsets

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "timestamp", "actor", "action", "entity_type", "entity_id", "summary", "data"]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only on purpose: the API offers no way to change history."""

    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    filterset_fields = ["entity_type", "entity_id", "action", "actor"]
