from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Append-only record of who did what, when (D-008).

    In aviation maintenance, "who signed this off and when" is a regulatory
    question, so rows here are never edited or deleted by the application.
    """

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=64)  # e.g. "component.installed"
    entity_type = models.CharField(max_length=64)  # e.g. "Component"
    entity_id = models.CharField(max_length=64)
    summary = models.CharField(max_length=255, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.action} {self.entity_type}#{self.entity_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("AuditLog rows are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditLog rows are append-only")
