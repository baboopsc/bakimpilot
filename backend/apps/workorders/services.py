"""
Work-order state machine and digital sign-off (D-017, D-018).

Every transition:
  * locks the work order row (no two people moving it at once),
  * checks the current status is one it may move from,
  * checks the actor is allowed (role + assignment + two-person rule),
  * writes an audit entry in the same transaction.
"""

import hashlib
import json
import uuid

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.services import record
from apps.fleet.models import Aircraft
from apps.maintenance.models import MaintenanceRule
from apps.maintenance.services import record_compliance
from config.exceptions import DomainError

from .models import ChecklistItem, WorkOrder

S = WorkOrder.Status
INSPECTOR_ROLES = {Role.ADMIN, Role.PLANNER}

# Which status each transition may start from.
ALLOWED_FROM = {
    "assign": {S.OPEN, S.IN_PROGRESS},
    "start": {S.OPEN},
    "checklist": {S.IN_PROGRESS},
    "tech_sign": {S.IN_PROGRESS},
    "certify": {S.AWAITING_INSPECTION},
    "reject": {S.AWAITING_INSPECTION},
    "cancel": {S.OPEN, S.IN_PROGRESS},
}


def _require(wo: WorkOrder, transition: str) -> None:
    if wo.status not in ALLOWED_FROM[transition]:
        raise DomainError(
            f"Can't {transition.replace('_', ' ')} a work order that is {wo.status}.", "bad_transition"
        )


def _lock(wo: WorkOrder) -> WorkOrder:
    return WorkOrder.objects.select_for_update().get(pk=wo.pk)


def _require_assignee(wo: WorkOrder, actor: User) -> None:
    if wo.assigned_to_id != actor.pk:
        raise DomainError("Only the assigned technician can do this.", "not_assignee")


def _verify_password(actor: User, password: str) -> None:
    # Re-entering the password makes signing a deliberate act by the account
    # owner, not something anyone at an unlocked screen can click.
    if not password or not actor.check_password(password):
        raise DomainError("Password confirmation failed.", "bad_signature_password")


def content_hash(wo: WorkOrder) -> str:
    """
    Fingerprint of exactly what the technician signed. If anybody later edits
    the checklist directly in the database, the hash no longer matches the
    stored signature, so tampering is detectable.
    """
    payload = {
        "number": wo.number,
        "aircraft": wo.aircraft_id,
        "component": wo.component_id,
        "rule": wo.rule_id,
        "title": wo.title,
        "checklist": [
            [i.position, i.text, i.done, i.done_by_id, i.note]
            for i in ChecklistItem.objects.filter(work_order=wo).order_by("position")
        ],
    }
    return _sha256(payload)


def _sha256(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _inspector_hash(wo: WorkOrder) -> str:
    # The inspector signs the technician's signature too: a chain, like a ledger.
    return _sha256(
        {"content": wo.tech_signature, "tech": wo.tech_signed_by_id, "inspector": wo.inspector_signed_by_id}
    )


def verify_signatures(wo: WorkOrder) -> bool:
    """True if nothing changed since signing."""
    if wo.tech_signature and content_hash(wo) != wo.tech_signature:
        return False
    if wo.inspector_signature and _inspector_hash(wo) != wo.inspector_signature:
        return False
    return True


@transaction.atomic
def create_work_order(
    *,
    actor: User,
    aircraft: Aircraft,
    title: str,
    checklist: list[str] | None = None,
    rule: MaintenanceRule | None = None,
    **fields,
) -> WorkOrder:
    component = fields.get("component")
    if component is not None:
        current = component.installations.filter(removed_at__isnull=True).first()
        if current and current.aircraft_id != aircraft.pk:
            raise DomainError("That component is installed on a different aircraft.", "component_mismatch")
    if fields.get("assigned_to") is not None and fields["assigned_to"].role != Role.TECHNICIAN:
        raise DomainError("Work orders can only be assigned to technicians.", "not_technician")

    items = list(checklist or (rule.checklist if rule else []))
    wo = WorkOrder.objects.create(
        number=f"TMP-{uuid.uuid4().hex[:16]}",
        aircraft=aircraft,
        title=title,
        rule=rule,
        created_by=actor,
        **fields,
    )
    # Number derived from the primary key: unique without any race between
    # two planners creating work orders at the same moment (D-017).
    wo.number = f"WO-{wo.created_at:%Y}-{wo.pk:05d}"
    wo.save(update_fields=["number"])
    ChecklistItem.objects.bulk_create(
        ChecklistItem(work_order=wo, position=n, text=text) for n, text in enumerate(items, start=1)
    )
    record(
        actor, "workorder.created", wo, f"Created {wo}", aircraft=aircraft.tail_number, grounding=wo.grounding
    )
    return wo


@transaction.atomic
def create_from_due_item(*, actor: User, key: str, assigned_to: User | None = None) -> WorkOrder:
    """Turn a line of the due list (e.g. "rule:3:component:12") into a work order."""
    from apps.fleet.models import Component
    from apps.maintenance.engine import OVERDUE, compute_due_items

    parts = key.split(":")
    if len(parts) != 4 or parts[0] != "rule" or parts[2] not in {"aircraft", "component"}:
        raise DomainError("Only rule-based due items can become work orders.", "bad_due_key")
    rule = MaintenanceRule.objects.get(pk=int(parts[1]))
    if parts[2] == "aircraft":
        aircraft, component = Aircraft.objects.get(pk=int(parts[3])), None
    else:
        component = Component.objects.get(pk=int(parts[3]))
        inst = component.installations.filter(removed_at__isnull=True).first()
        if inst is None:
            raise DomainError("Component is not installed.", "not_installed")
        aircraft = inst.aircraft

    if (
        WorkOrder.objects.filter(rule=rule, aircraft=aircraft, component=component)
        .exclude(status__in=[S.CLOSED, S.CANCELLED])
        .exists()
    ):
        raise DomainError("An open work order already exists for this task.", "duplicate")

    item = next((i for i in compute_due_items(aircraft_ids=[aircraft.pk]) if i.key == key), None)
    overdue = item is not None and item.status == OVERDUE
    return create_work_order(
        actor=actor,
        aircraft=aircraft,
        component=component,
        rule=rule,
        title=rule.name,
        description=rule.description,
        priority=WorkOrder.Priority.HIGH if overdue else WorkOrder.Priority.NORMAL,
        due_date=item.projected_due_date if item else None,
        assigned_to=assigned_to,
    )


@transaction.atomic
def assign(*, actor: User, wo: WorkOrder, technician: User) -> WorkOrder:
    wo = _lock(wo)
    _require(wo, "assign")
    if technician.role != Role.TECHNICIAN or not technician.is_active:
        raise DomainError("Work orders can only be assigned to active technicians.", "not_technician")
    wo.assigned_to = technician
    wo.save(update_fields=["assigned_to"])
    record(actor, "workorder.assigned", wo, f"Assigned {wo.number} to {technician.username}")
    return wo


@transaction.atomic
def start(*, actor: User, wo: WorkOrder) -> WorkOrder:
    wo = _lock(wo)
    _require(wo, "start")
    _require_assignee(wo, actor)
    wo.status, wo.started_at = S.IN_PROGRESS, timezone.now()
    wo.save(update_fields=["status", "started_at"])
    record(actor, "workorder.started", wo, f"Started {wo.number}")
    return wo


@transaction.atomic
def set_checklist_item(
    *, actor: User, wo: WorkOrder, item_id: int, done: bool, note: str = ""
) -> ChecklistItem:
    wo = _lock(wo)
    _require(wo, "checklist")
    _require_assignee(wo, actor)
    item = wo.checklist.get(pk=item_id)
    item.done = done
    item.note = note
    item.done_by = actor if done else None
    item.done_at = timezone.now() if done else None
    item.save()
    record(
        actor,
        "workorder.checklist",
        wo,
        f"{wo.number} #{item.position} {'done' if done else 'undone'}",
        note=note,
    )
    return item


@transaction.atomic
def tech_sign_off(*, actor: User, wo: WorkOrder, password: str) -> WorkOrder:
    wo = _lock(wo)
    _require(wo, "tech_sign")
    _require_assignee(wo, actor)
    _verify_password(actor, password)
    if wo.checklist.filter(done=False).exists():
        raise DomainError("All checklist items must be completed before sign-off.", "checklist_incomplete")
    wo.tech_signature = content_hash(wo)
    if wo.component_id:
        target = wo.component.__class__.objects.get(pk=wo.component_id)
        wo.hours_at_signoff, wo.cycles_at_signoff = target.hours_since_new, target.cycles_since_new
    else:
        target = Aircraft.objects.get(pk=wo.aircraft_id)
        wo.hours_at_signoff, wo.cycles_at_signoff = target.total_hours, target.total_cycles
    wo.tech_signed_by, wo.tech_signed_at = actor, timezone.now()
    wo.status = S.AWAITING_INSPECTION
    wo.save()
    record(actor, "workorder.tech_signed", wo, f"Technician signed {wo.number}", signature=wo.tech_signature)
    return wo


@transaction.atomic
def certify(*, actor: User, wo: WorkOrder, password: str) -> WorkOrder:
    """Inspector release. Closes the WO and records rule compliance."""
    wo = _lock(wo)
    _require(wo, "certify")
    if actor.role not in INSPECTOR_ROLES:
        raise DomainError("Only planners or admins can certify.", "not_inspector")
    if actor.pk == wo.tech_signed_by_id:
        raise DomainError("The inspector must be a different person from the technician.", "two_person_rule")
    _verify_password(actor, password)
    if not verify_signatures(wo):
        raise DomainError("Work order content changed after the technician signed.", "signature_mismatch")

    now = timezone.now()
    wo.inspector_signed_by, wo.inspector_signed_at = actor, now
    wo.inspector_signature = _inspector_hash(wo)
    wo.status, wo.closed_at = S.CLOSED, now
    wo.save()

    if wo.rule_id:
        # The maintenance task is now done: this resets its due counters.
        record_compliance(
            actor=actor,
            rule=wo.rule,
            aircraft=None if wo.component_id else wo.aircraft,
            component=wo.component,
            performed_at=wo.tech_signed_at,
            hours_at=wo.hours_at_signoff,
            cycles_at=wo.cycles_at_signoff,
            notes=f"Work order {wo.number}",
            work_order=wo,
        )
    record(
        actor,
        "workorder.certified",
        wo,
        f"Inspector certified and closed {wo.number}",
        signature=wo.inspector_signature,
    )
    return wo


@transaction.atomic
def reject(*, actor: User, wo: WorkOrder, reason: str) -> WorkOrder:
    """Inspector sends work back; the technician must redo and re-sign."""
    wo = _lock(wo)
    _require(wo, "reject")
    if actor.role not in INSPECTOR_ROLES:
        raise DomainError("Only planners or admins can reject.", "not_inspector")
    wo.status = S.IN_PROGRESS
    wo.tech_signed_by = wo.tech_signed_at = None
    wo.tech_signature = ""
    wo.save()
    record(actor, "workorder.rejected", wo, f"Inspection rejected {wo.number}: {reason}", reason=reason)
    return wo


@transaction.atomic
def cancel(*, actor: User, wo: WorkOrder, reason: str) -> WorkOrder:
    wo = _lock(wo)
    _require(wo, "cancel")
    wo.status, wo.cancel_reason = S.CANCELLED, reason
    wo.save(update_fields=["status", "cancel_reason"])
    record(actor, "workorder.cancelled", wo, f"Cancelled {wo.number}: {reason}", reason=reason)
    return wo
