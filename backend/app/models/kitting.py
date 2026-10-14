"""Kitting templates and the per-device checklist copied from them."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ASSET_TYPES, Base, TimestampMixin, in_list


class KittingTemplate(TimestampMixin, Base):
    """A reusable checklist for one device type.

    steps is a JSON list of {"en": "...", "ja": "..."} objects in execution order.
    """

    __tablename__ = "kitting_templates"
    __table_args__ = (
        CheckConstraint(in_list("device_type", ASSET_TYPES), name="device_type"),
        CheckConstraint("jsonb_typeof(steps) = 'array'", name="steps_is_array"),
        Index("ix_kitting_templates_device_type", "device_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class KittingTask(TimestampMixin, Base):
    """One checklist step for one device, copied from a template when kitting starts.

    step_en and step_ja are copies, so later template edits do not rewrite
    the record of what was actually done.

    run_no counts kitting runs per device. A re-kit (wiped -> in_stock -> kitting)
    starts run_no + 1, so earlier checklists are kept as history (approved decision).
    """

    __tablename__ = "kitting_tasks"
    __table_args__ = (
        CheckConstraint("step_no >= 1", name="step_no_positive"),
        CheckConstraint("run_no >= 1", name="run_no_positive"),
        UniqueConstraint("asset_id", "run_no", "step_no", name="uq_kitting_tasks_asset_run_step"),
        # A completed step must record when it was done; an open step must not.
        CheckConstraint(
            "(done AND done_at IS NOT NULL) OR (NOT done AND done_at IS NULL AND done_by IS NULL)",
            name="done_fields_consistent",
        ),
        Index("ix_kitting_tasks_asset_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    run_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    step_no: Mapped[int] = mapped_column(Integer)
    step_en: Mapped[str] = mapped_column(String(200))
    step_ja: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
