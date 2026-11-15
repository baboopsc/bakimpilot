"""
Spare parts stock as a ledger (D-019).

`StockMovement` rows are the source of truth (every receipt, issue and
adjustment, with who/why). `SparePart.quantity_on_hand` is the running
balance, updated under a row lock, and the database refuses to let it go
below zero.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q


class SparePart(models.Model):
    part_number = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    unit = models.CharField(max_length=16, default="pcs")  # pcs, L, kg, m
    location = models.CharField(max_length=64, blank=True)  # e.g. "Hangar 2 / Shelf B4"
    quantity_on_hand = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal(0), editable=False
    )
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0))  # reorder point

    class Meta:
        ordering = ["part_number"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity_on_hand__gte=0), name="stock_never_negative")
        ]

    def __str__(self) -> str:
        return f"{self.part_number} {self.name}"

    @property
    def is_low(self) -> bool:
        return self.quantity_on_hand <= self.min_quantity


class StockMovement(models.Model):
    class Reason(models.TextChoices):
        RECEIPT = "RECEIPT", "Received"
        ISSUE = "ISSUE", "Issued to work order"
        RETURN = "RETURN", "Returned from work order"
        ADJUSTMENT = "ADJUSTMENT", "Stock count adjustment"

    part = models.ForeignKey(SparePart, on_delete=models.PROTECT, related_name="movements")
    delta = models.DecimalField(max_digits=10, decimal_places=2)  # + in, - out
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    work_order = models.ForeignKey(
        "workorders.WorkOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="parts_used"
    )
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=~Q(delta=0), name="movement_not_zero")]

    def __str__(self) -> str:
        return f"{self.part.part_number} {self.delta:+} ({self.reason})"
