"""Schema for the dashboard summary."""

from datetime import date

from pydantic import BaseModel


class KittingProgress(BaseModel):
    """A device in kitting and how far its current run is."""

    asset_id: int
    asset_tag: str
    model: str
    done: int
    total: int
    percent: int


class WarrantyItem(BaseModel):
    """A device whose warranty ends soon."""

    asset_id: int
    asset_tag: str
    model: str
    warranty_end: date


class DashboardSummary(BaseModel):
    """All dashboard figures. Every count map lists all keys, including zeros.

    total_devices and devices_by_type exclude retired devices (the active fleet);
    devices_by_status includes retired so the lifecycle picture is complete.
    Open tickets are tickets that are open or in progress.
    """

    total_devices: int
    devices_by_type: dict[str, int]
    devices_by_status: dict[str, int]
    kitting: list[KittingProgress]
    overdue_loans: int
    non_compliant_devices: int
    warranty_window_days: int
    warranties_ending: list[WarrantyItem]
    open_tickets: int
    open_tickets_by_priority: dict[str, int]
    open_tickets_by_category: dict[str, int]
