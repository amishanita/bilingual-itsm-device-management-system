"""Audit log responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    """One audit row. user_email is empty for system actions such as the seed."""

    id: int
    created_at: datetime
    user_id: int | None
    user_email: str | None
    action: str
    entity: str
    entity_id: int
    detail: dict[str, Any]
