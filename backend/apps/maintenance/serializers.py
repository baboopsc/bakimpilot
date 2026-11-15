from rest_framework import serializers

from apps.fleet.models import Aircraft, Component

from .models import MaintenanceRecord, MaintenanceRule


class MaintenanceRuleSerializer(serializers.ModelSerializer):
    part_number = serializers.CharField(source="part_type.part_number", read_only=True, default=None)

    class Meta:
        model = MaintenanceRule
        fields = [
            "id",
            "code",
            "name",
            "description",
            "applies_to",
            "aircraft_model",
            "part_type",
            "part_number",
            "interval_hours",
            "interval_cycles",
            "interval_days",
            "checklist",
            "is_active",
        ]

    def validate(self, attrs):
        # Run the model's clean() on the would-be result, so the API and the
        # admin enforce exactly the same rules.
        candidate = MaintenanceRule()
        if self.instance:
            for f in MaintenanceRule._meta.concrete_fields:
                setattr(candidate, f.attname, getattr(self.instance, f.attname))
        for key, value in attrs.items():
            setattr(candidate, key, value)
        candidate.clean()
        return attrs


class MaintenanceRecordSerializer(serializers.ModelSerializer):
    rule_code = serializers.CharField(source="rule.code", read_only=True)
    performed_by = serializers.CharField(source="performed_by.username", read_only=True, default=None)
    aircraft = serializers.PrimaryKeyRelatedField(
        queryset=Aircraft.objects.all(), required=False, allow_null=True
    )
    component = serializers.PrimaryKeyRelatedField(
        queryset=Component.objects.all(), required=False, allow_null=True
    )
    hours_at = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    cycles_at = serializers.IntegerField(min_value=0, required=False)
    performed_at = serializers.DateTimeField(required=False)

    class Meta:
        model = MaintenanceRecord
        fields = [
            "id",
            "rule",
            "rule_code",
            "aircraft",
            "component",
            "performed_at",
            "hours_at",
            "cycles_at",
            "performed_by",
            "notes",
            "created_at",
        ]
        read_only_fields = ["performed_by", "created_at"]


class MeasureSerializer(serializers.Serializer):
    unit = serializers.CharField()
    interval = serializers.DecimalField(max_digits=12, decimal_places=2)
    used = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.CharField()
    projected_date = serializers.DateField(allow_null=True)


class DueItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    aircraft_id = serializers.IntegerField(allow_null=True)
    tail_number = serializers.CharField(allow_null=True)
    component_id = serializers.IntegerField(allow_null=True)
    component_label = serializers.CharField(allow_null=True)
    rule_id = serializers.IntegerField(allow_null=True)
    last_done = serializers.DateField(allow_null=True)
    projected_due_date = serializers.DateField(allow_null=True)
    measures = MeasureSerializer(many=True)


class AirworthinessSerializer(serializers.Serializer):
    aircraft_id = serializers.IntegerField()
    tail_number = serializers.CharField()
    status = serializers.CharField()
    reasons = serializers.ListField(child=serializers.CharField())
    overdue = serializers.IntegerField()
    due_soon = serializers.IntegerField()
