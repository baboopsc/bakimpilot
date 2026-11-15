from typing import Any

from django.db import models

from .models import AuditLog


def record(actor, action: str, obj: models.Model, summary: str = "", **data: Any) -> AuditLog:
    """
    Write one audit entry. Called explicitly from service functions (not via
    signals) so it's obvious in the code which actions are audited, and the
    entry is written inside the same DB transaction as the change itself.
    """
    return AuditLog.objects.create(
        actor=actor if (actor and actor.is_authenticated) else None,
        action=action,
        entity_type=obj.__class__.__name__,
        entity_id=str(obj.pk),
        summary=summary[:255],
        data=_jsonable(data),
    )


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # Decimal, datetime, date, model instances...
