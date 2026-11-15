from django.contrib import admin

from .models import ChecklistItem, WorkOrder


class ChecklistInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "aircraft", "status", "priority", "assigned_to")
    list_filter = ("status", "priority", "grounding")
    inlines = [ChecklistInline]

    def has_change_permission(self, request, obj=None):
        return False  # state changes only through the API (signatures, audit)
