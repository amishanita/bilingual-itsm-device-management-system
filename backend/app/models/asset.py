"""Company devices (assets) and their lifecycle status."""

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    ASSET_STATUSES,
    ASSET_TYPES,
    HELD_ASSET_STATUSES,
    Base,
    TimestampMixin,
    in_list,
)
from app.models.employee import Employee


class Asset(TimestampMixin, Base):
    """A physical device tracked from purchase to disposal.

    Assets are never hard-deleted. Disposal is the status "retired", so loan,
    ticket, kitting, and audit history always keep a valid reference.
    """

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(in_list("type", ASSET_TYPES), name="type"),
        CheckConstraint(in_list("status", ASSET_STATUSES), name="status"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="cost_not_negative"),
        CheckConstraint(
            "warranty_end IS NULL OR purchase_date IS NULL OR warranty_end >= purchase_date",
            name="warranty_after_purchase",
        ),
        # Business rule: assigned_to is set exactly when the device is assigned, on loan,
        # or in repair.
        # Enforcing it here means no code path can leave a holder on an unheld device.
        CheckConstraint(
            f"({in_list('status', HELD_ASSET_STATUSES)}) = (assigned_to IS NOT NULL)",
            name="assigned_to_matches_status",
        ),
        Index("ix_assets_status", "status"),
        Index("ix_assets_type", "type"),
        Index("ix_assets_assigned_to", "assigned_to"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(30), unique=True)
    type: Mapped[str] = mapped_column(String(20))
    serial_number: Mapped[str] = mapped_column(String(100), unique=True)
    manufacturer: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    # Purchase price in yen.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    location: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="ordered", server_default="ordered")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    notes: Mapped[str | None] = mapped_column(Text)

    holder: Mapped[Employee | None] = relationship()
