from django.contrib import admin

from .models import MaintenanceRecord, MaintenanceRule


@admin.register(MaintenanceRule)
class MaintenanceRuleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "applies_to",
        "interval_hours",
        "interval_cycles",
        "interval_days",
        "is_active",
    )
    list_filter = ("applies_to", "is_active")


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("rule", "aircraft", "component", "performed_at", "hours_at", "cycles_at")

    def has_change_permission(self, request, obj=None):
        return False
