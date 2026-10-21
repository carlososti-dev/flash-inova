import uuid

from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    entity: str | None = None,
    entity_id: object = None,
    details: dict | None = None,
) -> None:
    db.add(AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
    ))
