"""
Rebuild every running total from the raw flight logs and compare.

    python manage.py verify_counters

Exits non-zero if anything disagrees, so it can run as a scheduled job.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.fleet.models import Aircraft, Component
from apps.fleet.services import expected_aircraft_usage, expected_component_usage


class Command(BaseCommand):
    help = "Verify denormalised hour/cycle counters against flight logs."

    def handle(self, *args, **options):
        problems = []
        for aircraft in Aircraft.objects.all():
            hours, cycles = expected_aircraft_usage(aircraft)
            if (hours, cycles) != (aircraft.total_hours, aircraft.total_cycles):
                problems.append(
                    f"{aircraft}: stored {aircraft.total_hours}h/{aircraft.total_cycles}c, expected {hours}h/{cycles}c"
                )
        for comp in Component.objects.select_related("part_type"):
            hours, cycles = expected_component_usage(comp)
            if (hours, cycles) != (comp.hours_since_new, comp.cycles_since_new):
                problems.append(
                    f"{comp}: stored {comp.hours_since_new}h/{comp.cycles_since_new}c, expected {hours}h/{cycles}c"
                )
        if problems:
            for p in problems:
                self.stderr.write(p)
            raise CommandError(f"{len(problems)} counter mismatch(es)")
        self.stdout.write(self.style.SUCCESS("All counters match flight logs."))
