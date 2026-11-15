from rest_framework import serializers

from apps.accounts.models import Role, User
from apps.fleet.models import Aircraft, Component
from apps.maintenance.models import MaintenanceRule

from .models import ChecklistItem, WorkOrder


class ChecklistItemSerializer(serializers.ModelSerializer):
    done_by = serializers.CharField(source="done_by.username", read_only=True, default=None)

    class Meta:
        model = ChecklistItem
        fields = ["id", "position", "text", "done", "done_by", "done_at", "note"]
        read_only_fields = fields


class WorkOrderSerializer(serializers.ModelSerializer):
    aircraft = serializers.PrimaryKeyRelatedField(queryset=Aircraft.objects.all())
    component = serializers.PrimaryKeyRelatedField(
        queryset=Component.objects.all(), required=False, allow_null=True
    )
    rule = serializers.PrimaryKeyRelatedField(
        queryset=MaintenanceRule.objects.all(), required=False, allow_null=True
    )
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=Role.TECHNICIAN, is_active=True), required=False, allow_null=True
    )
    checklist = ChecklistItemSerializer(many=True, read_only=True)
    checklist_items = serializers.ListField(
        child=serializers.CharField(max_length=255), write_only=True, required=False
    )
    tail_number = serializers.CharField(source="aircraft.tail_number", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.username", read_only=True, default=None)
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    tech_signed_by = serializers.CharField(source="tech_signed_by.username", read_only=True, default=None)
    inspector_signed_by = serializers.CharField(
        source="inspector_signed_by.username", read_only=True, default=None
    )
    progress = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "number",
            "title",
            "description",
            "aircraft",
            "tail_number",
            "component",
            "rule",
            "grounding",
            "priority",
            "status",
            "due_date",
            "assigned_to",
            "assigned_to_name",
            "created_by",
            "created_at",
            "started_at",
            "tech_signed_by",
            "tech_signed_at",
            "tech_signature",
            "hours_at_signoff",
            "cycles_at_signoff",
            "inspector_signed_by",
            "inspector_signed_at",
            "inspector_signature",
            "closed_at",
            "cancel_reason",
            "checklist",
            "checklist_items",
            "progress",
        ]
        read_only_fields = [
            "number",
            "status",
            "created_at",
            "started_at",
            "tech_signed_at",
            "tech_signature",
            "hours_at_signoff",
            "cycles_at_signoff",
            "inspector_signed_at",
            "inspector_signature",
            "closed_at",
            "cancel_reason",
        ]

    def get_progress(self, obj) -> dict:
        items = list(obj.checklist.all())
        return {"done": sum(i.done for i in items), "total": len(items)}


class WorkOrderUpdateSerializer(serializers.ModelSerializer):
    """Only descriptive fields can change; status moves only through actions."""

    class Meta:
        model = WorkOrder
        fields = ["title", "description", "priority", "due_date", "grounding"]


class PasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class AssignSerializer(serializers.Serializer):
    technician = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class ChecklistUpdateSerializer(serializers.Serializer):
    item = serializers.IntegerField()
    done = serializers.BooleanField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class FromDueItemSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=Role.TECHNICIAN, is_active=True), required=False, allow_null=True
    )
