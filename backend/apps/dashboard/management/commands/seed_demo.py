"""
Fill the database with a realistic demo fleet.

    python manage.py seed_demo          # only if the DB has no aircraft yet
    python manage.py seed_demo --reset  # wipe everything first (demo/dev only!)

Everything goes through the real service functions, so counters, audit log,
alerts and signatures are exactly what real usage would produce.
Deterministic: the same random seed gives the same fleet every time.
"""

import hashlib
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.ai import rag
from apps.ai.models import ManualDocument
from apps.ai.pdfgen import build_pdf
from apps.ai.tasks import run_anomaly_scan
from apps.alerts.tasks import run_due_check, run_stock_check
from apps.fleet import services as fleet
from apps.fleet.models import Aircraft, PartType
from apps.inventory import services as stock
from apps.inventory.models import SparePart
from apps.maintenance.models import MaintenanceRule
from apps.maintenance.services import record_compliance
from apps.workorders import services as wo

DEMO_PASSWORD = "BakimPilot2026!"

AIRCRAFT = [
    # tail, model, days in service, typical hours per day of flying
    ("TB2-T001", "TB2", 400, 6.0),
    ("TB2-T002", "TB2", 380, 5.5),
    ("TB2-T003", "TB2", 300, 7.0),  # will show a vibration anomaly
    ("TB2-T004", "TB2", 250, 4.0),
    ("AKN-A001", "AKINCI", 200, 9.0),
    ("AKN-A002", "AKINCI", 150, 8.0),
]

PART_TYPES = [
    # part number, name, life hours, life cycles, life days, positions per model
    ("ENG-912", "Piston engine", Decimal("1500"), None, None),
    ("PRP-3B", "Propeller assembly", Decimal("600"), None, 1460),
    ("SRV-L10", "Flight control servo", Decimal("2000"), 6000, None),
    ("BAT-28V", "28V main battery", None, None, 365),
    ("LGR-M", "Main landing gear", None, 1200, None),
]
POSITIONS = {
    "ENG-912": ["ENGINE"],
    "PRP-3B": ["PROPELLER"],
    "SRV-L10": ["SERVO-L", "SERVO-R"],
    "BAT-28V": ["BATTERY"],
    "LGR-M": ["MLG"],
}

RULES = [
    (
        "TB2-50H",
        "50 h airframe inspection",
        "AIRCRAFT_MODEL",
        "TB2",
        None,
        Decimal(50),
        None,
        None,
        [
            "Visual inspection of airframe and wing roots",
            "Check control surface hinges and free play",
            "Inspect antennas and data link connectors",
            "Download and review flight data logs",
        ],
    ),
    (
        "TB2-90D",
        "90 day calendar check",
        "AIRCRAFT_MODEL",
        "TB2",
        None,
        None,
        None,
        90,
        ["Corrosion inspection", "Pitot-static system leak test", "Firmware version check"],
    ),
    (
        "AKN-100H",
        "100 h airframe inspection",
        "AIRCRAFT_MODEL",
        "AKINCI",
        None,
        Decimal(100),
        120,
        None,
        [
            "Airframe structural inspection",
            "Landing gear shock strut check",
            "Engine mount bolt torque check",
        ],
    ),
    (
        "ENG-100H",
        "Engine oil change & filter",
        "PART_TYPE",
        "",
        "ENG-912",
        Decimal(100),
        None,
        180,
        ["Drain oil and take sample", "Replace oil filter", "Refill and leak check"],
    ),
    (
        "PRP-200H",
        "Propeller balance check",
        "PART_TYPE",
        "",
        "PRP-3B",
        Decimal(200),
        None,
        None,
        ["Dynamic balance measurement", "Inspect blades for nicks"],
    ),
]

SPARES = [
    ("FLT-OIL", "Oil filter", "pcs", "H1 / A2", 4, 6),
    ("OIL-15W50", "Engine oil 15W-50", "L", "H1 / Drum 3", 12, 40),
    ("SPK-PLUG", "Spark plug", "pcs", "H1 / A4", 8, 20),
    ("SRV-L10", "Flight control servo (spare)", "pcs", "H2 / B1", 1, 2),
    ("BAT-28V", "28V main battery (spare)", "pcs", "H2 / C1", 1, 0),  # out of stock → alert
    ("PRP-BOLT", "Propeller bolt set", "set", "H1 / A6", 2, 5),
]


class Command(BaseCommand):
    help = "Create a realistic demo fleet (users, aircraft, parts, flights, rules, work orders, stock)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete ALL data first.")

    def handle(self, *args, reset=False, **options):
        if reset:
            call_command("flush", interactive=False)
        elif Aircraft.objects.exists():
            raise CommandError("Database already has aircraft. Use --reset to wipe it first.")

        self.rng = random.Random(42)
        self.today = timezone.localdate()
        with transaction.atomic():
            users = self._users()
            types = self._part_types()
            aircraft = self._fleet(types, users["planner"])
            self._rules(types)
            self._flights(aircraft)
            self._baselines(aircraft, users["planner"])
            self._spares(users["planner"])
            self._work_orders(aircraft, users)
        self._manual(users["planner"])
        run_due_check()
        run_stock_check()
        run_anomaly_scan()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready. Log in as admin / planner / tech / tech2 / viewer with password {DEMO_PASSWORD}"
            )
        )

    # --- builders -----------------------------------------------------------

    def _users(self):
        spec = {
            "admin": Role.ADMIN,
            "planner": Role.PLANNER,
            "tech": Role.TECHNICIAN,
            "tech2": Role.TECHNICIAN,
            "viewer": Role.VIEWER,
        }
        names = {
            "admin": ("Ayşe", "Yılmaz"),
            "planner": ("Mehmet", "Kaya"),
            "tech": ("Elif", "Demir"),
            "tech2": ("Can", "Şahin"),
            "viewer": ("Zeynep", "Arslan"),
        }
        out = {}
        for username, role in spec.items():
            first, last = names[username]
            out[username] = User.objects.create_user(
                username,
                password=DEMO_PASSWORD,
                role=role,
                first_name=first,
                last_name=last,
                is_staff=role == Role.ADMIN,
                is_superuser=role == Role.ADMIN,
            )
        return out

    def _part_types(self):
        return {
            pn: PartType.objects.create(
                part_number=pn, name=name, life_limit_hours=h, life_limit_cycles=c, life_limit_days=d
            )
            for pn, name, h, c, d in PART_TYPES
        }

    def _dt(self, d: date, hour: float) -> datetime:
        return timezone.make_aware(datetime.combine(d, time(0))) + timedelta(hours=hour)

    def _fleet(self, types, planner):
        fleet_out = []
        serial = 1000
        for tail, model, age, _ in AIRCRAFT:
            in_service = self.today - timedelta(days=age)
            ac = fleet.create_aircraft(
                actor=planner,
                tail_number=tail,
                model=model,
                serial_number=f"{model}-{tail[-3:]}",
                in_service_date=in_service,
                # flying before the 60 days we simulate in detail
                initial_hours=Decimal(age - 60) * Decimal("2.1"),
                initial_cycles=(age - 60) // 2,
            )
            for pn, pt in types.items():
                for pos in POSITIONS[pn]:
                    serial += 1
                    made = in_service - timedelta(days=30)
                    # Parts get replaced over an aircraft's life, so each starts with
                    # a believable share of its own life used (not the aircraft's hours).
                    life_h = pt.life_limit_hours or Decimal(3000)
                    used_h = (life_h * Decimal(str(self.rng.uniform(0.05, 0.3)))).quantize(Decimal("0.01"))
                    used_c = min(ac.initial_cycles, (pt.life_limit_cycles or 10000) // 4)
                    if pn == "BAT-28V":
                        made = self.today - timedelta(days=self.rng.choice([120, 200, 340, 352]))
                        used_h, used_c = Decimal(0), 0
                    if pn == "ENG-912" and tail == "TB2-T002":
                        used_h = Decimal("1200")  # will end up close to its 1500 h life
                    comp = fleet.create_component(
                        actor=planner,
                        part_type=pt,
                        serial_number=f"{pn}-{serial}",
                        manufacture_date=made,
                        initial_hours=used_h,
                        initial_cycles=used_c,
                    )
                    fleet.install_component(
                        actor=planner,
                        component=comp,
                        aircraft=ac,
                        position=pos,
                        at=self._dt(self.today - timedelta(days=61), 8),
                    )
            fleet_out.append(ac)
        # one spare engine in stores
        fleet.create_component(
            actor=planner,
            part_type=types["ENG-912"],
            serial_number="ENG-912-SPARE",
            manufacture_date=self.today - timedelta(days=90),
        )
        return fleet_out

    def _rules(self, types):
        for code, name, applies, model, pn, h, c, d, checklist in RULES:
            MaintenanceRule.objects.create(
                code=code,
                name=name,
                applies_to=applies,
                aircraft_model=model,
                part_type=types[pn] if pn else None,
                interval_hours=h,
                interval_cycles=c,
                interval_days=d,
                checklist=checklist,
            )

    def _flights(self, aircraft):
        """60 days of sorties with sensor summaries. TB2-T003 develops rising vibration in the last week."""
        for ac, (_, _, _, per_day) in zip(aircraft, AIRCRAFT, strict=True):
            for back in range(60, 0, -1):
                d = self.today - timedelta(days=back)
                if self.rng.random() < 0.25:
                    continue  # no flying that day
                hours = max(1.0, self.rng.gauss(per_day, 1.2))
                start = self._dt(d, self.rng.uniform(5, 9))
                vib = self.rng.gauss(0.42, 0.03)
                temp = self.rng.gauss(96 if ac.model == "TB2" else 104, 2.5)
                if ac.tail_number == "TB2-T003" and back <= 7:
                    vib += 0.06 * (8 - back)  # creeping vibration: propeller imbalance?
                    temp += 1.2 * (8 - back)
                fleet.log_flight(
                    actor=None,
                    aircraft=ac,
                    takeoff_at=start,
                    landing_at=start + timedelta(hours=round(hours, 2)),
                    cycles=1,
                    mission=self.rng.choice(["ISR patrol", "Training", "Border surveillance", "Test flight"]),
                    max_engine_temp_c=Decimal(f"{temp:.1f}"),
                    avg_vibration_g=Decimal(f"{vib:.3f}"),
                    fuel_used_l=Decimal(
                        f"{hours * (11 if ac.model == 'TB2' else 38) * self.rng.uniform(0.9, 1.1):.2f}"
                    ),
                )

    def _baselines(self, aircraft, planner):
        """Record when tasks were last done, so the due list is realistic (a few overdue, some due soon)."""
        for ac in aircraft:
            ac.refresh_from_db()
            for rule in MaintenanceRule.objects.filter(aircraft_model=ac.model):
                behind = Decimal(self.rng.choice([10, 25, 38, 47, 55])) if rule.interval_hours else Decimal(0)
                days_ago = self.rng.choice([20, 60, 85, 95]) if rule.interval_days else 5
                record_compliance(
                    actor=planner,
                    rule=rule,
                    aircraft=ac,
                    performed_at=self._dt(self.today - timedelta(days=days_ago), 10),
                    hours_at=max(Decimal(0), ac.total_hours - behind),
                    cycles_at=max(0, ac.total_cycles - int(behind / 6)),
                    notes="Baseline imported from legacy spreadsheet",
                )
            for inst in ac.installations.filter(removed_at__isnull=True).select_related("component"):
                comp = inst.component
                for rule in MaintenanceRule.objects.filter(part_type_id=comp.part_type_id):
                    behind = Decimal(self.rng.choice([20, 60, 90, 150]))
                    record_compliance(
                        actor=planner,
                        rule=rule,
                        component=comp,
                        performed_at=self._dt(
                            self.today - timedelta(days=self.rng.choice([30, 100, 170])), 10
                        ),
                        hours_at=max(Decimal(0), comp.hours_since_new - behind),
                        cycles_at=comp.cycles_since_new,
                        notes="Baseline imported from legacy spreadsheet",
                    )

    def _spares(self, planner):
        for pn, name, unit, loc, min_q, qty in SPARES:
            part = SparePart.objects.create(
                part_number=pn, name=name, unit=unit, location=loc, min_quantity=min_q
            )
            if qty:
                stock.receive(actor=planner, part=part, quantity=Decimal(qty), note="Initial stock count")

    def _work_orders(self, aircraft, users):
        planner, tech, tech2 = users["planner"], users["tech"], users["tech2"]
        t001, t002, t003 = aircraft[0], aircraft[1], aircraft[2]
        rule_50 = MaintenanceRule.objects.get(code="TB2-50H")

        # 1. Closed, fully signed 50 h inspection on T001
        w = wo.create_work_order(
            actor=planner, aircraft=t001, title=rule_50.name, rule=rule_50, assigned_to=tech
        )
        wo.start(actor=tech, wo=w)
        for item in w.checklist.all():
            wo.set_checklist_item(actor=tech, wo=w, item_id=item.pk, done=True, note="No findings")
        filt = SparePart.objects.get(part_number="FLT-OIL")
        stock.issue_to_work_order(actor=tech, part=filt, quantity=Decimal(1), work_order=w)
        wo.tech_sign_off(actor=tech, wo=w, password=DEMO_PASSWORD)
        wo.certify(actor=planner, wo=w, password=DEMO_PASSWORD)

        # 2. In progress on T002, half done
        w = wo.create_work_order(
            actor=planner, aircraft=t002, title=rule_50.name, rule=rule_50, assigned_to=tech2
        )
        wo.start(actor=tech2, wo=w)
        first = w.checklist.first()
        wo.set_checklist_item(
            actor=tech2, wo=w, item_id=first.pk, done=True, note="Minor paint chip, within limits"
        )

        # 3. Grounding defect on T003 (the one with the vibration trend)
        wo.create_work_order(
            actor=planner,
            aircraft=t003,
            title="Investigate rising vibration reported by ground station",
            description="Vibration trend flagged after last sorties. Check propeller balance and engine mounts.",
            grounding=True,
            priority="HIGH",
            assigned_to=tech,
            checklist=[
                "Dynamic propeller balance",
                "Engine mount visual + torque",
                "Review vibration spectrum",
            ],
        )

    def _manual(self, planner):
        """A small fictional manual so the RAG assistant has something to answer from."""
        pdf = build_pdf(DEMO_MANUAL)
        doc = ManualDocument(
            title="TB2 Line Maintenance Manual (demo)",
            aircraft_model="TB2",
            uploaded_by=planner,
            sha256=hashlib.sha256(pdf).hexdigest(),
        )
        doc.file.save("tb2-line-maintenance-demo.pdf", ContentFile(pdf), save=True)
        rag.ingest(doc)


DEMO_MANUAL = [
    [
        "TB2 LINE MAINTENANCE MANUAL - DEMO EDITION (fictional data for software demonstration)",
        "",
        "Chapter 1 - General safety",
        "1.1 Disconnect the 28V main battery before any work on the engine or avionics.",
        "1.2 Two-person rule: every task in this manual must be inspected by a person other than",
        "the technician who performed it before the aircraft is released to service.",
        "1.3 Ground the aircraft immediately if any limit in this manual is exceeded.",
    ],
    [
        "Chapter 2 - Engine oil change (task ENG-100H)",
        "2.1 Interval: every 100 flight hours or 180 days, whichever comes first.",
        "2.2 Run the engine for 3 minutes so the oil is warm, then shut down.",
        "2.3 Remove the drain plug and drain the oil into an approved container.",
        "2.4 Take a 50 ml oil sample for spectrometric analysis.",
        "2.5 Replace the oil filter (part number FLT-OIL). Lightly oil the new gasket.",
        "2.6 Torque the oil drain plug to 25 Nm and secure it with lock wire.",
        "2.7 Refill with 3.2 litres of 15W-50 aviation oil.",
        "2.8 Run the engine for 5 minutes and check for leaks.",
    ],
    [
        "Chapter 3 - Propeller",
        "3.1 Maximum allowed propeller vibration is 0.55 g at cruise power.",
        "3.2 If average vibration exceeds 0.55 g on two consecutive flights, perform a dynamic",
        "balance check (task PRP-200H) before the next flight.",
        "3.3 Inspect blades for nicks deeper than 0.5 mm; blend out or replace the propeller.",
        "3.4 Propeller bolts (PRP-BOLT) must be torqued to 18 Nm in a cross pattern.",
        "3.5 Propeller life limit: 600 flight hours or 4 years, whichever comes first.",
    ],
    [
        "Chapter 4 - Engine temperature",
        "4.1 Normal maximum engine temperature in cruise is 90 to 102 degrees C.",
        "4.2 Above 110 degrees C: land as soon as practical and inspect the cooling inlets.",
        "4.3 A gradual rise over several flights often indicates low oil level or blocked baffles.",
        "4.4 Verify the temperature sensor before replacing engine parts: compare with a",
        "calibrated handheld thermometer.",
    ],
    [
        "Chapter 5 - 28V main battery",
        "5.1 Battery calendar life is 365 days from manufacture date, regardless of use.",
        "5.2 Capacity test every 90 days; replace if capacity is below 80 percent.",
        "5.3 Store spare batteries at 15 to 25 degrees C with 50 percent charge.",
    ],
]
