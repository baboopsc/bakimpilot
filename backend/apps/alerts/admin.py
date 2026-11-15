from django.contrib import admin

from .models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "severity", "created_at", "resolved_at")
    list_filter = ("kind", "severity")
