"""Audit log writer.

Callers add the audit row to the same session as the business change and
commit once, so the change and its audit record succeed or fail together.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User

# Keys that must never reach audit details, whatever a caller passes in.
FORBIDDEN_DETAIL_KEYS = frozenset(
    {"password", "password_hash", "new_password", "current_password", "token", "access_token"}
)


def record(
    db: Session,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: int,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row to the session without committing.

    Raises ValueError if detail contains a secret field, so a mistake in a
    caller fails loudly instead of leaking a password into the log.
    """
    detail = detail or {}
    leaked = FORBIDDEN_DETAIL_KEYS.intersection(detail)
    if leaked:
        raise ValueError(f"Audit detail must not contain: {', '.join(sorted(leaked))}")
    entry = AuditLog(
        user_id=actor.id if actor else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        detail=detail,
    )
    db.add(entry)
    return entry
