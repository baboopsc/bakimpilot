"""
Fleet: aircraft, serialized components, where each component is installed,
and the flights that wear them out.

Life is measured three ways (D-010):
  * flight hours  — time in the air
  * cycles        — one take-off + landing (stresses landing gear, airframe)
  * calendar days — rubber, batteries and seals age even on the ground
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

ZERO = Decimal("0.00")


class Aircraft(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        STORED = "STORED", "Stored"  # parked long-term, excluded from readiness
        RETIRED = "RETIRED", "Retired"

    tail_number = models.CharField(max_length=32, unique=True)  # e.g. "TB2-T042"
    model = models.CharField(max_length=64)  # e.g. "TB2"
    serial_number = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    in_service_date = models.DateField()
    # Usage before the aircraft entered BakımPilot (e.g. acceptance test flights).
    initial_hours = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    initial_cycles = models.PositiveIntegerField(default=0)
    # Running totals since new. Kept up to date by fleet.services (denormalised
    # for speed; `recompute_*` can rebuild them from flight logs — D-011).
    total_hours = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total_cycles = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tail_number"]
        verbose_name_plural = "aircraft"

    def __str__(self) -> str:
        return self.tail_number


class PartType(models.Model):
    """
    A catalog entry: "what kind of part this is" (shared by many serial numbers).

    Life limits live here, because the manufacturer sets them per part number,
    not per individual unit. Any limit may be empty (= not limited that way).
    """

    part_number = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    life_limit_hours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    life_limit_cycles = models.PositiveIntegerField(null=True, blank=True)
    life_limit_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["part_number"]

    def __str__(self) -> str:
        return f"{self.part_number} {self.name}"


class Component(models.Model):
    """One physical, serialized part (e.g. engine S/N ENG-1001)."""

    class Status(models.TextChoices):
        SERVICEABLE = "SERVICEABLE", "Serviceable"
        UNSERVICEABLE = "UNSERVICEABLE", "Unserviceable"  # removed for repair/inspection
        SCRAPPED = "SCRAPPED", "Scrapped"  # end of life, can never be installed again

    part_type = models.ForeignKey(PartType, on_delete=models.PROTECT, related_name="components")
    serial_number = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SERVICEABLE)
    manufacture_date = models.DateField()  # calendar life counts from here
    # Usage since new (TSN = time since new, CSN = cycles since new). Includes
    # usage the part had before it entered our system (`initial_*`).
    initial_hours = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    initial_cycles = models.PositiveIntegerField(default=0)
    hours_since_new = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    cycles_since_new = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["part_type__part_number", "serial_number"]
        constraints = [
            models.UniqueConstraint(fields=["part_type", "serial_number"], name="uniq_part_serial"),
        ]

    def __str__(self) -> str:
        return f"{self.part_type.part_number} S/N {self.serial_number}"

    @property
    def current_installation(self):
        return self.installations.filter(removed_at__isnull=True).select_related("aircraft").first()


class Installation(models.Model):
    """
    Install/remove history: one row per period a component spent on an aircraft.
    `removed_at` empty = still installed. Rows are never deleted (traceability).
    """

    component = models.ForeignKey(Component, on_delete=models.PROTECT, related_name="installations")
    aircraft = models.ForeignKey(Aircraft, on_delete=models.PROTECT, related_name="installations")
    position = models.CharField(max_length=64)  # e.g. "ENGINE", "LEFT_WING_SERVO"
    installed_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True, blank=True)
    removal_reason = models.CharField(max_length=255, blank=True)
    # Snapshot of aircraft + component counters at install time.
    aircraft_hours_at_install = models.DecimalField(max_digits=10, decimal_places=2)
    aircraft_cycles_at_install = models.PositiveIntegerField()
    component_hours_at_install = models.DecimalField(max_digits=10, decimal_places=2)
    component_cycles_at_install = models.PositiveIntegerField()

    class Meta:
        ordering = ["-installed_at"]
        constraints = [
            # The database itself guarantees a part is never in two places at
            # once, and a position never holds two parts (D-012).
            models.UniqueConstraint(
                fields=["component"],
                condition=Q(removed_at__isnull=True),
                name="one_open_install_per_component",
            ),
            models.UniqueConstraint(
                fields=["aircraft", "position"],
                condition=Q(removed_at__isnull=True),
                name="one_component_per_open_position",
            ),
            models.CheckConstraint(
                condition=Q(removed_at__isnull=True) | Q(removed_at__gte=models.F("installed_at")),
                name="removed_after_installed",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.component} on {self.aircraft} @ {self.position}"


class FlightLog(models.Model):
    """
    One flight. Saving it (through fleet.services.log_flight) adds its hours and
    cycles to the aircraft and to every component installed at take-off time.

    The sensor summary fields feed the anomaly detector (apps.ai).
    """

    aircraft = models.ForeignKey(Aircraft, on_delete=models.PROTECT, related_name="flights")
    takeoff_at = models.DateTimeField()
    landing_at = models.DateTimeField()
    cycles = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    duration_hours = models.DecimalField(max_digits=6, decimal_places=2, editable=False)
    mission = models.CharField(max_length=128, blank=True)
    # Flight-data summary (optional; filled by ground station / ingestion service)
    max_engine_temp_c = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    avg_vibration_g = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    fuel_used_l = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=32, default="manual")  # manual | ingest
    external_id = models.CharField(max_length=64, null=True, blank=True, unique=True)  # idempotent ingestion
    logged_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-takeoff_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(landing_at__gt=models.F("takeoff_at")), name="landing_after_takeoff"
            ),
        ]
        indexes = [models.Index(fields=["aircraft", "takeoff_at"])]

    def __str__(self) -> str:
        return f"{self.aircraft} {self.takeoff_at:%Y-%m-%d %H:%M} ({self.duration_hours} h)"
