"""Schemas for login account management (super_admin only)."""

from datetime import datetime
from typing import ClassVar, Literal

from app.schemas.auth import Language, NewPassword, UserProfile
from app.schemas.common import Email, PartialUpdate, StrictModel

Role = Literal["super_admin", "it_admin", "manager", "employee"]


class UserCreate(StrictModel):
    """Body for POST /api/users."""

    email: Email
    password: NewPassword
    role: Role
    employee_id: int | None = None
    language: Language = "ja"


class UserUpdate(PartialUpdate):
    """Body for PUT /api/users/{id}. Every field is optional.

    Sending "employee_id": null unlinks the employee; leaving the field out
    keeps the current link. "password" resets the password.
    """

    NULLABLE: ClassVar[frozenset[str]] = frozenset({"employee_id"})

    role: Role | None = None
    is_active: bool | None = None
    employee_id: int | None = None
    password: NewPassword | None = None
    language: Language | None = None


class UserOut(UserProfile):
    """A login account as shown to super_admin. Never includes the password hash."""

    created_at: datetime
    updated_at: datetime
