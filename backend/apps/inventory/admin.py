from django.contrib import admin

from .models import SparePart, StockMovement


@admin.register(SparePart)
class SparePartAdmin(admin.ModelAdmin):
    list_display = ("part_number", "name", "quantity_on_hand", "min_quantity", "location")
    readonly_fields = ("quantity_on_hand",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("part", "delta", "balance_after", "reason", "work_order", "created_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
