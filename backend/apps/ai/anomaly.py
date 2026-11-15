"""
Flight-data anomaly detection + explanation (D-026).

Detection is plain statistics, deterministic and testable. The LLM only
*explains* what statistics already found, so a model can never invent an
anomaly or hide one.

Method (robust z-score): for each aircraft and metric, compare the last
RECENT flights against the BASELINE flights before them using the median
and MAD (median absolute deviation). Unlike mean/stdev, these aren't
dragged around by the outliers we're trying to find.

    z = 0.6745 * (value - median) / MAD

A metric is flagged when at least 2 of the recent flights exceed |z| > 3.5
(a common cut-off for robust z-scores). Requiring two flights avoids alerting
on one noisy sensor reading. The latest value is also reported, so a
creeping trend shows.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

from apps.alerts.models import Alert
from apps.alerts.services import Problem, sync_alerts
from apps.fleet.models import Aircraft, FlightLog

from .providers import LLMUnavailable, get_llm

RECENT = 5
BASELINE = 30
MIN_BASELINE = 10
Z_THRESHOLD = 3.5
MIN_FLAGGED = 2

METRICS = {
    "avg_vibration_g": ("Average vibration", "g"),
    "max_engine_temp_c": ("Max engine temperature", "°C"),
    "fuel_per_hour_l": ("Fuel burn per flight hour", "L/h"),
}

HINTS = {
    "avg_vibration_g": [
        "Dynamic propeller balance check",
        "Inspect propeller blades for nicks, erosion or delamination",
        "Check engine mount bolts and isolators",
        "Compare against the vibration limit in the engine/propeller manual",
    ],
    "max_engine_temp_c": [
        "Check oil level and recent oil analysis",
        "Inspect cooling air inlets and baffles for blockage",
        "Verify temperature sensor and wiring (rule out a sensor fault)",
        "Review mixture/ignition settings with the engine manual",
    ],
    "fuel_per_hour_l": [
        "Inspect fuel lines and fittings for leaks",
        "Check fuel flow sensor calibration",
        "Review mission profile: heavier payload or headwinds raise burn legitimately",
    ],
}


@dataclass
class Anomaly:
    aircraft_id: int
    tail_number: str
    metric: str
    label: str
    unit: str
    baseline_median: float
    baseline_mad: float
    recent_values: list[float]
    recent_z: list[float]
    flagged_flights: int
    direction: str  # "high" | "low"

    @property
    def key(self) -> str:
        return f"anomaly:{self.aircraft_id}:{self.metric}"


def robust_z(values: list[float], baseline: list[float]) -> tuple[float, float, list[float]]:
    med = statistics.median(baseline)
    mad = statistics.median(abs(v - med) for v in baseline)
    if mad == 0:
        # Perfectly constant baseline: fall back to a small fraction of the median
        # so a real change still registers without dividing by zero.
        mad = max(abs(med) * 0.01, 1e-6)
    return med, mad, [0.6745 * (v - med) / mad for v in values]


def _series(flights, metric: str) -> list[float]:
    out = []
    for fl in flights:
        if metric == "fuel_per_hour_l":
            if fl.fuel_used_l is not None and fl.duration_hours:
                out.append(float(fl.fuel_used_l / fl.duration_hours))
        else:
            v = getattr(fl, metric)
            if v is not None:
                out.append(float(v))
    return out


def detect(aircraft: Aircraft) -> list[Anomaly]:
    flights = list(FlightLog.objects.filter(aircraft=aircraft).order_by("-takeoff_at")[: RECENT + BASELINE])
    flights.reverse()  # oldest → newest
    found = []
    for metric, (label, unit) in METRICS.items():
        series = _series(flights, metric)
        if len(series) < RECENT + MIN_BASELINE:
            continue  # not enough history to say what "normal" is
        baseline, recent = series[:-RECENT], series[-RECENT:]
        med, mad, zs = robust_z(recent, baseline)
        flagged = [z for z in zs if abs(z) > Z_THRESHOLD]
        if len(flagged) >= MIN_FLAGGED:
            found.append(
                Anomaly(
                    aircraft.pk,
                    aircraft.tail_number,
                    metric,
                    label,
                    unit,
                    round(med, 3),
                    round(mad, 4),
                    [round(v, 3) for v in recent],
                    [round(z, 1) for z in zs],
                    len(flagged),
                    "high" if sum(flagged) > 0 else "low",
                )
            )
    return found


def scan_fleet() -> list[Anomaly]:
    out = []
    for ac in Aircraft.objects.filter(status=Aircraft.Status.ACTIVE):
        out.extend(detect(ac))
    return out


def sync_anomaly_alerts() -> dict:
    problems = [
        Problem(
            key=a.key,
            kind=Alert.Kind.ANOMALY,
            severity=Alert.Severity.WARNING,
            title=f"{a.tail_number}: unusual {a.label.lower()} ({a.direction})",
            message=f"Recent {a.recent_values} vs baseline median {a.baseline_median} {a.unit}",
            aircraft_id=a.aircraft_id,
            data={"metric": a.metric},
        )
        for a in scan_fleet()
    ]
    return sync_alerts(problems, kinds={Alert.Kind.ANOMALY}).__dict__


# --- explanation -------------------------------------------------------------

SYSTEM_PROMPT = """You are a UAV maintenance engineering assistant in BakımPilot. A statistical \
detector flagged a flight-data anomaly. Explain it for a maintenance planner in plain language:
1. What changed (use the numbers given; don't invent other measurements).
2. The most likely technical causes for this UAV/metric, most likely first, using the aircraft context.
3. Concrete checks to perform, in order.
Be explicit that this is advisory: airworthiness decisions are made by certifying staff following \
the approved maintenance manual. Keep it under 200 words. Answer in Turkish if asked in Turkish, \
otherwise English."""


def _context(a: Anomaly) -> str:
    ac = Aircraft.objects.get(pk=a.aircraft_id)
    comps = [
        f"{i.position}: {i.component} ({i.component.hours_since_new} h since new)"
        for i in ac.installations.filter(removed_at__isnull=True).select_related("component__part_type")
    ]
    wos = [f"{w.number} {w.title} [{w.status}]" for w in ac.work_orders.order_by("-created_at")[:5]]
    return (
        f"Aircraft {ac.tail_number} ({ac.model}), {ac.total_hours} h total.\n"
        f"Metric: {a.label} ({a.unit}). Baseline median {a.baseline_median}, MAD {a.baseline_mad}.\n"
        f"Last {len(a.recent_values)} flights, oldest first: {a.recent_values} (robust z: {a.recent_z}).\n"
        f"Installed components: {'; '.join(comps) or 'none recorded'}.\n"
        f"Recent work orders: {'; '.join(wos) or 'none'}."
    )


def template_explanation(a: Anomaly) -> str:
    """Deterministic explanation (mock provider / fallback)."""
    trend = "rising" if a.recent_values[-1] > a.recent_values[0] else "elevated"
    if a.direction == "low":
        trend = "lower than usual"
    checks = "\n".join(f"{n}. {h}" for n, h in enumerate(HINTS[a.metric], start=1))
    return (
        f"{a.label} on {a.tail_number} is {trend}: the last {len(a.recent_values)} flights read "
        f"{', '.join(map(str, a.recent_values))} {a.unit}, against a normal (median) of "
        f"{a.baseline_median} {a.unit}. {a.flagged_flights} of them are statistically unusual "
        f"(|z| > {Z_THRESHOLD}).\n\nSuggested checks:\n{checks}\n\n"
        "Advisory only: airworthiness decisions are made by certifying staff following the approved manual."
    )


def explain(a: Anomaly, *, language_hint: str = "") -> dict:
    llm = get_llm()
    if llm.is_mock:
        return {
            "explanation": template_explanation(a),
            "provider": "mock",
            "degraded": False,
            "anomaly": asdict(a),
        }
    try:
        prompt = _context(a) + (f"\n\nRespond in: {language_hint}" if language_hint else "")
        result = llm.complete(system=SYSTEM_PROMPT, prompt=prompt, max_tokens=2000)
        return {
            "explanation": result.text,
            "provider": llm.name,
            "model": result.model,
            "degraded": False,
            "anomaly": asdict(a),
        }
    except LLMUnavailable:
        return {
            "explanation": template_explanation(a),
            "provider": llm.name,
            "degraded": True,
            "anomaly": asdict(a),
        }
