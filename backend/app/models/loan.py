"""Short-term device loans and their return records."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import LOAN_CONDITIONS, Base, TimestampMixin, in_list


class DeviceLoan(TimestampMixin, Base):
    """A loan of one device to one employee.

    A loan is overdue when due_at has passed and returned_at is empty.
    Returned loans are kept as history.
    """

    __tablename__ = "device_loans"
    __table_args__ = (
        CheckConstraint(
            f"condition IS NULL OR {in_list('condition', LOAN_CONDITIONS)}", name="condition"
        ),
        CheckConstraint("due_at > lent_at", name="due_after_lent"),
        CheckConstraint(
            "returned_at IS NULL OR returned_at >= lent_at", name="returned_after_lent"
        ),
        # Returning a loan requires a condition, so a returned row always has one.
        CheckConstraint(
            "returned_at IS NULL OR condition IS NOT NULL", name="returned_has_condition"
        ),
        # Concurrency guard: at most one open loan per device, even if two
        # requests try to lend the same device at the same moment.
        Index(
            "uq_device_loans_one_open_loan_per_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL"),
        ),
        Index("ix_device_loans_employee_id", "employee_id"),
        Index("ix_device_loans_due_at", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    lent_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    lent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    condition: Mapped[str | None] = mapped_column(String(20))
    wipe_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    note: Mapped[str | None] = mapped_column(Text)
