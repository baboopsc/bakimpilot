from django.contrib import admin

from .models import Aircraft, Component, FlightLog, Installation, PartType


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ("tail_number", "model", "status", "total_hours", "total_cycles")
    readonly_fields = ("total_hours", "total_cycles")


@admin.register(PartType)
class PartTypeAdmin(admin.ModelAdmin):
    list_display = ("part_number", "name", "life_limit_hours", "life_limit_cycles", "life_limit_days")


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "hours_since_new", "cycles_since_new")
    readonly_fields = ("hours_since_new", "cycles_since_new")


@admin.register(Installation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ("component", "aircraft", "position", "installed_at", "removed_at")

    def has_change_permission(self, request, obj=None):
        return False  # history goes through services only


@admin.register(FlightLog)
class FlightLogAdmin(admin.ModelAdmin):
    list_display = ("aircraft", "takeoff_at", "duration_hours", "cycles", "source")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False  # must go through services.log_flight so counters update
