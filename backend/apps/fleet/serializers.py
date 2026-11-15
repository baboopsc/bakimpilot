from rest_framework import serializers

from .models import Aircraft, Component, FlightLog, Installation, PartType
from .services import life_remaining


class AircraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Aircraft
        fields = [
            "id",
            "tail_number",
            "model",
            "serial_number",
            "status",
            "in_service_date",
            "initial_hours",
            "initial_cycles",
            "total_hours",
            "total_cycles",
            "created_at",
        ]
        # Counters only ever change through flights (services.log_flight).
        read_only_fields = ["total_hours", "total_cycles", "created_at"]

    def update(self, instance, validated_data):
        validated_data.pop("initial_hours", None)  # baseline is fixed after creation
        validated_data.pop("initial_cycles", None)
        return super().update(instance, validated_data)


class PartTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartType
        fields = ["id", "part_number", "name", "life_limit_hours", "life_limit_cycles", "life_limit_days"]


class InstallationSerializer(serializers.ModelSerializer):
    aircraft_tail = serializers.CharField(source="aircraft.tail_number", read_only=True)
    component_label = serializers.CharField(source="component.__str__", read_only=True)

    class Meta:
        model = Installation
        fields = [
            "id",
            "component",
            "component_label",
            "aircraft",
            "aircraft_tail",
            "position",
            "installed_at",
            "removed_at",
            "removal_reason",
            "aircraft_hours_at_install",
            "aircraft_cycles_at_install",
            "component_hours_at_install",
            "component_cycles_at_install",
        ]
        read_only_fields = fields


class ComponentSerializer(serializers.ModelSerializer):
    part_number = serializers.CharField(source="part_type.part_number", read_only=True)
    part_name = serializers.CharField(source="part_type.name", read_only=True)
    installed_on = serializers.SerializerMethodField()
    life_remaining = serializers.SerializerMethodField()

    class Meta:
        model = Component
        fields = [
            "id",
            "part_type",
            "part_number",
            "part_name",
            "serial_number",
            "status",
            "manufacture_date",
            "initial_hours",
            "initial_cycles",
            "hours_since_new",
            "cycles_since_new",
            "installed_on",
            "life_remaining",
        ]
        read_only_fields = ["hours_since_new", "cycles_since_new"]

    def get_installed_on(self, obj):
        # Uses the prefetched open installations (see ComponentViewSet) to avoid N+1 queries.
        open_inst = [i for i in obj.installations.all() if i.removed_at is None]
        if not open_inst:
            return None
        inst = open_inst[0]
        return {
            "aircraft": inst.aircraft_id,
            "tail_number": inst.aircraft.tail_number,
            "position": inst.position,
        }

    def get_life_remaining(self, obj) -> dict:
        rem = life_remaining(obj)
        return {"hours": rem.hours, "cycles": rem.cycles, "days": rem.days, "expired": rem.expired}

    def update(self, instance, validated_data):
        for frozen in ("part_type", "initial_hours", "initial_cycles"):
            validated_data.pop(frozen, None)
        return super().update(instance, validated_data)


class InstallSerializer(serializers.Serializer):
    aircraft = serializers.PrimaryKeyRelatedField(queryset=Aircraft.objects.all())
    position = serializers.CharField(max_length=64)
    installed_at = serializers.DateTimeField(required=False)


class RemoveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    removed_at = serializers.DateTimeField(required=False)
    mark_unserviceable = serializers.BooleanField(default=False)


class FlightLogSerializer(serializers.ModelSerializer):
    aircraft_tail = serializers.CharField(source="aircraft.tail_number", read_only=True)
    logged_by = serializers.CharField(source="logged_by.username", read_only=True, default=None)

    class Meta:
        model = FlightLog
        fields = [
            "id",
            "aircraft",
            "aircraft_tail",
            "takeoff_at",
            "landing_at",
            "cycles",
            "duration_hours",
            "mission",
            "max_engine_temp_c",
            "avg_vibration_g",
            "fuel_used_l",
            "source",
            "external_id",
            "logged_by",
            "created_at",
        ]
        read_only_fields = ["duration_hours", "source", "logged_by", "created_at"]
