"""Read-only view of the audit trail. super_admin only."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import DbSession, SuperAdmin
from app.core.errors import AppError
from app.models import AuditLog, User
from app.schemas.audit import AuditLogOut
from app.schemas.common import Limit, Offset, Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])

Code = Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z_]+$")]


@router.get("", response_model=Page[AuditLogOut])
def list_audit_logs(
    db: DbSession,
    _admin: SuperAdmin,
    entity: Code = None,
    entity_id: Annotated[int | None, Query(ge=1)] = None,
    action: Code = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[AuditLogOut]:
    """Newest first. since and until are ISO 8601 times; since is inclusive, until exclusive."""
    if since and until and since >= until:
        raise AppError(400, "INVALID_TIME_RANGE", "since must be earlier than until.")
    query = select(AuditLog)
    if entity:
        query = query.where(AuditLog.entity == entity.lower())
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if action:
        query = query.where(AuditLog.action == action.upper())
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at < until)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.add_columns(User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        AuditLogOut(
            id=log.id,
            created_at=log.created_at,
            user_id=log.user_id,
            user_email=email,
            action=log.action,
            entity=log.entity,
            entity_id=log.entity_id,
            detail=log.detail or {},
        )
        for log, email in rows
    ]
    return Page[AuditLogOut](items=items, total=total)
