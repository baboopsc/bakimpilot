"""
Maintenance program: recurring tasks ("rules") and the records proving they were done.

A rule says: "do X every N hours / N cycles / N days, whichever comes first".
It applies either to every aircraft of a model (airframe tasks) or to every
component of a part type (component tasks, which follow the part when it
moves to another aircraft).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class MaintenanceRule(models.Model):
    class AppliesTo(models.TextChoices):
        AIRCRAFT_MODEL = "AIRCRAFT_MODEL", "Aircraft model"
        PART_TYPE = "PART_TYPE", "Part type"

    code = models.CharField(max_length=32, unique=True)  # e.g. "TB2-100H"
    name = models.CharField(max_length=128)  # e.g. "100-hour airframe inspection"
    description = models.TextField(blank=True)
    applies_to = models.CharField(max_length=16, choices=AppliesTo.choices)
    aircraft_model = models.CharField(max_length=64, blank=True)
    part_type = models.ForeignKey(
        "fleet.PartType", null=True, blank=True, on_delete=models.PROTECT, related_name="rules"
    )
    interval_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    interval_cycles = models.PositiveIntegerField(null=True, blank=True)
    interval_days = models.PositiveIntegerField(null=True, blank=True)
    # Default checklist copied into each work order created for this rule.
    checklist = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                name="rule_has_an_interval",
                condition=Q(interval_hours__isnull=False)
                | Q(interval_cycles__isnull=False)
                | Q(interval_days__isnull=False),
            ),
            models.CheckConstraint(
                name="rule_target_matches_kind",
                condition=(Q(applies_to="AIRCRAFT_MODEL") & ~Q(aircraft_model="") & Q(part_type__isnull=True))
                | (Q(applies_to="PART_TYPE") & Q(aircraft_model="") & Q(part_type__isnull=False)),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

    def clean(self):
        if not (self.interval_hours or self.interval_cycles or self.interval_days):
            raise ValidationError("A rule needs at least one interval (hours, cycles or days).")
        if self.applies_to == self.AppliesTo.AIRCRAFT_MODEL and (
            not self.aircraft_model or self.part_type_id
        ):
            raise ValidationError("Aircraft rules need an aircraft model and no part type.")
        if self.applies_to == self.AppliesTo.PART_TYPE and (not self.part_type_id or self.aircraft_model):
            raise ValidationError("Part rules need a part type and no aircraft model.")
        if not isinstance(self.checklist, list) or not all(isinstance(i, str) for i in self.checklist):
            raise ValidationError("Checklist must be a list of strings.")


class MaintenanceRecord(models.Model):
    """
    Proof that a rule was carried out on one aircraft or one component, with the
    counters at that moment. The next due point is measured from the latest record.
    """

    rule = models.ForeignKey(MaintenanceRule, on_delete=models.PROTECT, related_name="records")
    aircraft = models.ForeignKey(
        "fleet.Aircraft", null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_records"
    )
    component = models.ForeignKey(
        "fleet.Component", null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_records"
    )
    performed_at = models.DateTimeField()
    hours_at = models.DecimalField(max_digits=10, decimal_places=2)
    cycles_at = models.PositiveIntegerField()
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        constraints = [
            models.CheckConstraint(
                name="record_has_exactly_one_target",
                condition=(Q(aircraft__isnull=False) & Q(component__isnull=True))
                | (Q(aircraft__isnull=True) & Q(component__isnull=False)),
            )
        ]
        indexes = [models.Index(fields=["rule", "aircraft", "component", "-performed_at"])]

    def __str__(self) -> str:
        return f"{self.rule.code} on {self.aircraft or self.component} @ {self.performed_at:%Y-%m-%d}"
