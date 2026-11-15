"""
Work orders: the unit of maintenance work.

Lifecycle (D-017):

    OPEN ──start──▶ IN_PROGRESS ──tech sign-off──▶ AWAITING_INSPECTION ──certify──▶ CLOSED
      │                ▲                                   │
      │                └────────────── reject ─────────────┘
      └──────────── cancel (from OPEN / IN_PROGRESS) ──────────────▶ CANCELLED

Two different people must sign: the technician who did the work and an
inspector (planner/admin) who certifies it — the "two-person rule" used in
aviation maintenance for release to service.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class WorkOrder(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        AWAITING_INSPECTION = "AWAITING_INSPECTION", "Awaiting inspection"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        NORMAL = "NORMAL", "Normal"
        HIGH = "HIGH", "High"
        AOG = "AOG", "Aircraft on ground"

    number = models.CharField(max_length=20, unique=True, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    aircraft = models.ForeignKey("fleet.Aircraft", on_delete=models.PROTECT, related_name="work_orders")
    component = models.ForeignKey(
        "fleet.Component", null=True, blank=True, on_delete=models.PROTECT, related_name="work_orders"
    )
    rule = models.ForeignKey(
        "maintenance.MaintenanceRule",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="work_orders",
    )
    # True = the aircraft may not fly until this is closed (e.g. a defect found on walk-around).
    grounding = models.BooleanField(default=False)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    due_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_work_orders",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)

    tech_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tech_signed_at = models.DateTimeField(null=True, blank=True)
    tech_signature = models.CharField(max_length=64, blank=True)  # SHA-256 of the signed content
    # Counters of the maintained item (aircraft or component) at technician
    # sign-off: the next interval is measured from here, not from certification,
    # so hours flown while waiting for inspection are never lost.
    hours_at_signoff = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cycles_at_signoff = models.PositiveIntegerField(null=True, blank=True)
    inspector_signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    inspector_signed_at = models.DateTimeField(null=True, blank=True)
    inspector_signature = models.CharField(max_length=64, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="two_person_rule",
                condition=Q(inspector_signed_by__isnull=True)
                | ~Q(inspector_signed_by=models.F("tech_signed_by")),
            )
        ]
        indexes = [models.Index(fields=["status", "aircraft"])]

    def __str__(self) -> str:
        return f"{self.number} {self.title}"


class ChecklistItem(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="checklist")
    position = models.PositiveSmallIntegerField()
    text = models.CharField(max_length=255)
    done = models.BooleanField(default=False)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    done_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)  # e.g. measured value, finding

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["work_order", "position"], name="uniq_checklist_position")
        ]

    def __str__(self) -> str:
        return f"{self.work_order.number} #{self.position} {self.text}"
