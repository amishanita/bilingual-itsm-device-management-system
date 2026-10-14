"""Declarative base, shared timestamp columns, and the value lists stored as English codes."""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names so Alembic migrations stay predictable across databases.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Status, type, category, and priority values are stored as English codes.
# The frontend translates them; the database never stores display labels.
USER_ROLES = ("super_admin", "it_admin", "manager", "employee")
LANGUAGES = ("ja", "en")
EMPLOYEE_STATUSES = ("active", "on_leave", "left")
ASSET_TYPES = ("laptop", "desktop", "smartphone", "tablet", "monitor", "printer")
ASSET_STATUSES = (
    "ordered",
    "in_stock",
    "kitting",
    "ready",
    "assigned",
    "on_loan",
    "returned",
    "wiped",
    "repair",
    "retired",
)
# Statuses in which a device is held by an employee (assets.assigned_to is set).
HELD_ASSET_STATUSES = ("assigned", "on_loan")
COMPLIANCE_STATES = ("compliant", "non_compliant", "unknown")
LOAN_CONDITIONS = ("ok", "damaged", "missing_parts")
TICKET_CATEGORIES = (
    "password",
    "laptop",
    "smartphone",
    "tablet",
    "vpn",
    "email",
    "software",
    "hardware",
    "network",
    "account",
)
TICKET_PRIORITIES = ("low", "medium", "high", "critical")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_SOURCES = ("web", "chatbot")
CHAT_ROLES = ("user", "assistant", "tool")


def in_list(column: str, values: tuple[str, ...]) -> str:
    """Build a CHECK expression that limits a column to a fixed list of codes."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """UTC-aware created_at and updated_at columns.

    The database sets both on insert. updated_at is refreshed by SQLAlchemy on
    every ORM update.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
