from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    PLANNER = "PLANNER", "Maintenance planner"
    TECHNICIAN = "TECHNICIAN", "Technician"
    VIEWER = "VIEWER", "Viewer"


class User(AbstractUser):
    """Custom user from day one, so we can add fields later without painful migrations (D-004)."""

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    def has_role(self, *roles: str) -> bool:
        return self.is_active and self.role in roles

    def __str__(self) -> str:
        return f"{self.username} ({self.role})"
