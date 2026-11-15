"""
Natural-language questions over maintenance data (D-025).

    "Which aircraft are grounded?"  /  "T003'ün açık iş emirleri neler?"

The LLM never writes SQL. It only fills in a small, whitelisted QuerySpec
(which entity, which filters). Our own ORM code runs it. So:
  * no SQL injection, and no query that could modify data;
  * every query is something we've tested;
  * the user sees the interpreted spec, so a misunderstanding is visible.
Without an LLM, a rule-based parser (Turkish + English keywords) fills
the same spec.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Q
from django.utils import timezone

from apps.alerts.models import Alert
from apps.fleet.models import Aircraft, Component, FlightLog
from apps.fleet.services import life_remaining
from apps.inventory.models import SparePart
from apps.maintenance import engine
from apps.workorders.models import WorkOrder

from .providers import LLMUnavailable, get_llm

ENTITIES = ["aircraft", "due_items", "work_orders", "components", "flights", "spare_parts", "alerts"]
FILTERS = {
    "tail_number": "Aircraft tail number or a fragment of it, e.g. 'T003'",
    "airworthiness": "AIRWORTHY | ATTENTION | GROUNDED (aircraft only)",
    "status": "Entity status: due items OVERDUE|DUE_SOON|OK; work orders OPEN|IN_PROGRESS|AWAITING_INSPECTION|CLOSED|CANCELLED; components SERVICEABLE|UNSERVICEABLE|SCRAPPED; aircraft ACTIVE|STORED|RETIRED",
    "open_only": "Only open work orders / unresolved alerts",
    "within_days": "Due items projected due within N days; flights in the last N days",
    "part_number": "Part number fragment (components, spare parts)",
    "assigned_to": "Username of the technician (work orders)",
    "priority": "LOW|NORMAL|HIGH|AOG (work orders)",
    "severity": "INFO|WARNING|CRITICAL (alerts)",
    "low_stock": "Spare parts at or below reorder point",
    "life_remaining_hours_below": "Components with fewer remaining life hours than this",
}

_nullable = {"type": ["string", "null"]}
QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "entity": {"type": "string", "enum": ENTITIES},
        "filters": {
            "type": "object",
            "properties": {
                "tail_number": _nullable,
                "airworthiness": _nullable,
                "status": _nullable,
                "open_only": {"type": ["boolean", "null"]},
                "within_days": {"type": ["integer", "null"]},
                "part_number": _nullable,
                "assigned_to": _nullable,
                "priority": _nullable,
                "severity": _nullable,
                "low_stock": {"type": ["boolean", "null"]},
                "life_remaining_hours_below": {"type": ["number", "null"]},
            },
            "required": list(FILTERS),
            "additionalProperties": False,
        },
        "limit": {"type": "integer"},
        "explanation": {"type": "string"},
    },
    "required": ["entity", "filters", "limit", "explanation"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You translate questions from UAV maintenance staff into a query specification for the "
    "BakımPilot maintenance system. Pick the single best entity and set only the filters the "
    "question implies; leave every other filter null. Use limit 50 unless the question asks for "
    "fewer. In `explanation`, restate in one short sentence (in the question's language) what "
    "will be listed, so the user can spot a misunderstanding.\n\nFilters:\n"
    + "\n".join(f"- {k}: {v}" for k, v in FILTERS.items())
)

MAX_LIMIT = 200


# --- rule-based parser (mock provider / fallback) -----------------------------------

TAIL_RE = re.compile(r"\b([A-Z]{2,4}\d?-?[A-Z]?\d{3})\b|\b([A-Z]\d{3})\b", re.IGNORECASE)


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def rule_based_spec(question: str) -> dict:
    q = question.lower()
    f = dict.fromkeys(FILTERS)
    m = TAIL_RE.search(question)
    if m:
        f["tail_number"] = (m.group(1) or m.group(2)).upper()
    days = re.search(r"(\d+)\s*(gün|day)", q)
    if days:
        f["within_days"] = int(days.group(1))
    if _has(q, "next week", "gelecek hafta", "önümüzdeki hafta"):
        f["within_days"] = 7

    if _has(q, "stock", "stok", "spare", "yedek"):
        entity = "spare_parts"
        f["low_stock"] = True if _has(q, "low", "düşük", "az", "biten", "out of") else None
    elif _has(q, "alert", "uyarı", "alarm"):
        entity = "alerts"
        f["open_only"] = True
        if _has(q, "critical", "kritik"):
            f["severity"] = "CRITICAL"
    elif _has(q, "work order", "iş emri", "is emri", "iş emirleri"):
        entity = "work_orders"
        if _has(q, "open", "açık", "acik", "pending", "bekleyen"):
            f["open_only"] = True
        if _has(q, "inspection", "onay", "denetim"):
            f["status"] = "AWAITING_INSPECTION"
        if _has(q, "aog", "urgent", "acil"):
            f["priority"] = "AOG"
        who = re.search(r"(?:assigned to|atanan)\s+(\w+)", q)
        if who:
            f["assigned_to"] = who.group(1)
    elif _has(q, "flight", "uçuş", "ucus", "sorti"):
        entity = "flights"
        f["within_days"] = f["within_days"] or 30
    elif _has(
        q, "component", "part", "parça", "parca", "engine", "motor", "battery", "batarya", "life", "ömür"
    ):
        entity = "components"
        hours = re.search(r"(\d+)\s*(h\b|hour|saat)", q)
        if hours or _has(q, "life", "ömür"):
            f["life_remaining_hours_below"] = float(hours.group(1)) if hours else 100.0
        pn = re.search(r"\b([A-Z]{3}-[A-Z0-9]+)\b", question)
        if pn:
            f["part_number"] = pn.group(1)
    elif _has(
        q, "due", "overdue", "vade", "gecik", "geçmiş", "yaklaşan", "bakım", "maintenance", "inspection"
    ):
        entity = "due_items"
        if _has(q, "overdue", "gecik", "geçmiş", "gecmis"):
            f["status"] = "OVERDUE"
        elif _has(q, "soon", "yaklaşan", "yakında", "upcoming"):
            f["status"] = "DUE_SOON"
        if f["within_days"] is None and f["status"] is None:
            f["within_days"] = 30
    else:
        entity = "aircraft"
        if _has(q, "grounded", "yerde", "uçamaz", "ucamaz", "not airworthy"):
            f["airworthiness"] = "GROUNDED"
        elif _has(q, "airworthy", "uçuşa elverişli", "ready", "hazır"):
            f["airworthiness"] = "AIRWORTHY"
    return {"entity": entity, "filters": f, "limit": 50, "explanation": ""}


# --- execution ---------------------------------------------------------------


def _tail_q(prefix: str, value: str | None) -> Q:
    return Q(**{f"{prefix}tail_number__icontains": value}) if value else Q()


def _run_aircraft(f):
    qs = Aircraft.objects.filter(_tail_q("", f["tail_number"]))
    if f["status"] in Aircraft.Status.values:
        qs = qs.filter(status=f["status"])
    statuses = {
        s.aircraft_id: s
        for s in engine.fleet_airworthiness(aircraft_ids=list(qs.values_list("pk", flat=True)))
    }
    rows = []
    for ac in qs:
        st = statuses.get(ac.pk)
        aw = st.status if st else "RETIRED"
        if f["airworthiness"] and aw != f["airworthiness"]:
            continue
        rows.append(
            {
                "tail_number": ac.tail_number,
                "model": ac.model,
                "airworthiness": aw,
                "total_hours": ac.total_hours,
                "reasons": "; ".join(st.reasons[:3]) if st else "",
            }
        )
    return rows


def _run_due_items(f):
    items = engine.compute_due_items()
    today = timezone.localdate()
    rows = []
    for i in items:
        if f["tail_number"] and f["tail_number"].lower() not in (i.tail_number or "").lower():
            continue
        if f["status"] in (engine.OK, engine.DUE_SOON, engine.OVERDUE) and i.status != f["status"]:
            continue
        if f["within_days"] is not None and i.status != engine.OVERDUE:
            if not i.projected_due_date or i.projected_due_date > today + timedelta(days=f["within_days"]):
                continue
        rows.append(
            {
                "tail_number": i.tail_number,
                "title": i.title,
                "status": i.status,
                "projected_due_date": i.projected_due_date,
                "remaining": ", ".join(f"{m.remaining} {m.unit}" for m in i.measures),
            }
        )
    return rows


def _run_work_orders(f):
    qs = WorkOrder.objects.select_related("aircraft", "assigned_to").filter(
        _tail_q("aircraft__", f["tail_number"])
    )
    if f["open_only"]:
        qs = qs.exclude(status__in=[WorkOrder.Status.CLOSED, WorkOrder.Status.CANCELLED])
    if f["status"] in WorkOrder.Status.values:
        qs = qs.filter(status=f["status"])
    if f["priority"]:
        qs = qs.filter(priority=f["priority"])
    if f["assigned_to"]:
        qs = qs.filter(assigned_to__username__iexact=f["assigned_to"])
    return [
        {
            "number": w.number,
            "tail_number": w.aircraft.tail_number,
            "title": w.title,
            "status": w.status,
            "priority": w.priority,
            "assigned_to": w.assigned_to.username if w.assigned_to else None,
        }
        for w in qs
    ]


def _run_components(f):
    qs = Component.objects.select_related("part_type").prefetch_related("installations__aircraft")
    if f["part_number"]:
        qs = qs.filter(part_type__part_number__icontains=f["part_number"])
    if f["status"] in Component.Status.values:
        qs = qs.filter(status=f["status"])
    if f["tail_number"]:
        qs = qs.filter(
            installations__removed_at__isnull=True,
            installations__aircraft__tail_number__icontains=f["tail_number"],
        )
    rows = []
    for c in qs.distinct():
        rem = life_remaining(c)
        if f["life_remaining_hours_below"] is not None and (
            rem.hours is None or rem.hours >= Decimal(str(f["life_remaining_hours_below"]))
        ):
            continue
        inst = next((i for i in c.installations.all() if i.removed_at is None), None)
        rows.append(
            {
                "component": str(c),
                "status": c.status,
                "installed_on": inst.aircraft.tail_number if inst else None,
                "hours_since_new": c.hours_since_new,
                "life_remaining_hours": rem.hours,
                "life_remaining_days": rem.days,
            }
        )
    return sorted(rows, key=lambda r: (r["life_remaining_hours"] is None, r["life_remaining_hours"] or 0))


def _run_flights(f):
    since = timezone.now() - timedelta(days=f["within_days"] or 30)
    qs = (
        FlightLog.objects.select_related("aircraft")
        .filter(takeoff_at__gte=since)
        .filter(_tail_q("aircraft__", f["tail_number"]))
    )
    return [
        {
            "tail_number": fl.aircraft.tail_number,
            "takeoff_at": fl.takeoff_at,
            "hours": fl.duration_hours,
            "mission": fl.mission,
            "max_engine_temp_c": fl.max_engine_temp_c,
            "avg_vibration_g": fl.avg_vibration_g,
        }
        for fl in qs
    ]


def _run_spare_parts(f):
    qs = SparePart.objects.all()
    if f["low_stock"]:
        qs = qs.filter(quantity_on_hand__lte=F("min_quantity"))
    if f["part_number"]:
        qs = qs.filter(part_number__icontains=f["part_number"])
    return [
        {
            "part_number": p.part_number,
            "name": p.name,
            "on_hand": p.quantity_on_hand,
            "reorder_point": p.min_quantity,
        }
        for p in qs
    ]


def _run_alerts(f):
    qs = Alert.objects.select_related("aircraft").filter(_tail_q("aircraft__", f["tail_number"]))
    if f["open_only"] is not False:
        qs = qs.filter(resolved_at__isnull=True)
    if f["severity"]:
        qs = qs.filter(severity=f["severity"])
    return [
        {
            "title": a.title,
            "severity": a.severity,
            "kind": a.kind,
            "created_at": a.created_at,
            "message": a.message,
        }
        for a in qs
    ]


RUNNERS = {
    "aircraft": _run_aircraft,
    "due_items": _run_due_items,
    "work_orders": _run_work_orders,
    "components": _run_components,
    "flights": _run_flights,
    "spare_parts": _run_spare_parts,
    "alerts": _run_alerts,
}


def normalise(spec: dict) -> dict:
    """Never trust model output blindly: coerce to the whitelist even after schema validation."""
    entity = spec.get("entity") if spec.get("entity") in RUNNERS else "aircraft"
    raw = spec.get("filters") or {}
    filters = {k: raw.get(k) for k in FILTERS}
    try:
        limit = max(1, min(int(spec.get("limit") or 50), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 50
    return {
        "entity": entity,
        "filters": filters,
        "limit": limit,
        "explanation": str(spec.get("explanation") or ""),
    }


def describe(spec: dict) -> str:
    active = {k: v for k, v in spec["filters"].items() if v not in (None, "", False)}
    cond = ", ".join(f"{k}={v}" for k, v in active.items()) or "no filters"
    return f"Listing {spec['entity'].replace('_', ' ')} ({cond})."


def run_query(question: str) -> dict:
    llm = get_llm()
    degraded, model = False, ""
    if llm.is_mock:
        spec = rule_based_spec(question)
    else:
        try:
            spec = llm.complete_json(
                system=SYSTEM_PROMPT, prompt=question, schema=QUERY_SCHEMA, max_tokens=2000
            )
            model = getattr(llm, "model", "")
        except LLMUnavailable:
            spec, degraded = rule_based_spec(question), True
    spec = normalise(spec)
    if not spec["explanation"]:
        spec["explanation"] = describe(spec)
    rows = RUNNERS[spec["entity"]](spec["filters"])
    return {
        "question": question,
        "spec": spec,
        "count": len(rows),
        "rows": rows[: spec["limit"]],
        "provider": llm.name,
        "model": model,
        "degraded": degraded,
    }
