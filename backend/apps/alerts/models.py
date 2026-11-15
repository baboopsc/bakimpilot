from django.conf import settings
from django.db import models
from django.db.models import Q


class Alert(models.Model):
    """
    Something a human should look at. Alerts are raised and resolved by
    scheduled checks (apps.alerts.tasks), never typed in by hand.

    `dedup_key` identifies the underlying problem (e.g. "rule:3:aircraft:7").
    Only one *open* alert per key can exist, so the hourly check doesn't spam
    the same warning every hour (D-016).
    """

    class Kind(models.TextChoices):
        DUE_SOON = "DUE_SOON", "Maintenance due soon"
        OVERDUE = "OVERDUE", "Maintenance overdue"
        LOW_STOCK = "LOW_STOCK", "Low stock"
        ANOMALY = "ANOMALY", "Flight data anomaly"

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    dedup_key = models.CharField(max_length=128)
    aircraft = models.ForeignKey(
        "fleet.Aircraft", null=True, blank=True, on_delete=models.CASCADE, related_name="alerts"
    )
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedup_key"], condition=Q(resolved_at__isnull=True), name="one_open_alert_per_key"
            )
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"
