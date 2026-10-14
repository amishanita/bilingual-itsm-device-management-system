"""Technical details for one device. Autopilot and Intune fields are recorded manually."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import COMPLIANCE_STATES, Base, TimestampMixin, in_list


class DeviceDetail(TimestampMixin, Base):
    """One row per asset, keyed by the asset id.

    These values are entered by IT staff. This version does not sync with
    Microsoft Autopilot or Intune.
    """

    __tablename__ = "device_details"
    __table_args__ = (
        CheckConstraint(in_list("compliance", COMPLIANCE_STATES), name="compliance"),
        CheckConstraint("ram_gb IS NULL OR ram_gb >= 0", name="ram_not_negative"),
        CheckConstraint("storage_gb IS NULL OR storage_gb >= 0", name="storage_not_negative"),
    )

    # The detail row belongs to its asset, so it is removed with it. Assets are
    # retired rather than deleted, so this only matters for administrative cleanup.
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    os: Mapped[str | None] = mapped_column(String(50))
    os_version: Mapped[str | None] = mapped_column(String(50))
    cpu: Mapped[str | None] = mapped_column(String(100))
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    mac_address: Mapped[str | None] = mapped_column(String(17))
    imei: Mapped[str | None] = mapped_column(String(20))
    phone_number: Mapped[str | None] = mapped_column(String(20))
    carrier: Mapped[str | None] = mapped_column(String(50))
    sim_iccid: Mapped[str | None] = mapped_column(String(22))
    autopilot_registered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    mdm_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    encryption_on: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    compliance: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    last_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
