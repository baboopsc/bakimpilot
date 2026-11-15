"""Test data builders (factory_boy): create valid objects with one line."""

from datetime import date
from decimal import Decimal

import factory

from apps.fleet.models import Aircraft, Component, PartType


class AircraftFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Aircraft

    tail_number = factory.Sequence(lambda n: f"TB-{n:03d}")
    model = "TB2"
    serial_number = factory.Sequence(lambda n: f"AC-SN-{n:04d}")
    in_service_date = date(2024, 1, 1)


class PartTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PartType

    part_number = factory.Sequence(lambda n: f"PN-{n:04d}")
    name = "Engine"
    life_limit_hours = Decimal("1000.00")
    life_limit_cycles = 2000
    life_limit_days = None


class ComponentFactory(factory.django.DjangoModelFactory):
    """Note: bypasses services.create_component, so set *_since_new explicitly if needed."""

    class Meta:
        model = Component

    part_type = factory.SubFactory(PartTypeFactory)
    serial_number = factory.Sequence(lambda n: f"SN-{n:05d}")
    manufacture_date = date(2024, 1, 1)
