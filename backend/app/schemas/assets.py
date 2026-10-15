"""Schemas for assets, device details, status changes, and device history."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import PartialUpdate, StrictModel

AssetType = Literal["laptop", "desktop", "smartphone", "tablet", "monitor", "printer"]
AssetStatus = Literal[
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
]
# A new asset starts either on order or already in stock. Every later status is
# reached only through the lifecycle endpoint.
InitialStatus = Literal["ordered", "in_stock"]
Compliance = Literal["compliant", "non_compliant", "unknown"]


# Trimmed, non-empty strings with database-matching length limits.
Str30 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
Str50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Str100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Cost = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Notes = Annotated[str, StringConstraints(max_length=2000)]


class WarrantyCheck:
    """Mixin: the warranty cannot end before the purchase date."""

    purchase_date: date | None
    warranty_end: date | None

    @model_validator(mode="after")
    def warranty_after_purchase(self) -> Self:
        """Reject a warranty end date earlier than the purchase date."""
        if self.purchase_date and self.warranty_end and self.warranty_end < self.purchase_date:
            raise ValueError("warranty_end cannot be earlier than purchase_date")
        return self


class AssetCreate(WarrantyCheck, StrictModel):
    """Body for POST /api/assets. The holder is never set here."""

    asset_tag: Str30
    type: AssetType
    serial_number: Str100
    manufacturer: Str100
    model: Str100
    purchase_date: date | None = None
    warranty_end: date | None = None
    cost: Cost | None = None
    location: Str100 | None = None
    notes: Notes | None = None
    status: InitialStatus = "ordered"


class AssetUpdate(WarrantyCheck, PartialUpdate):
    """Body for PUT /api/assets/{id}.

    status and assigned_to are deliberately absent: they change only through
    POST /api/assets/{id}/status, where the lifecycle rules are enforced.
    """

    NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {"purchase_date", "warranty_end", "cost", "location", "notes"}
    )

    asset_tag: Str30 | None = None
    type: AssetType | None = None
    serial_number: Str100 | None = None
    manufacturer: Str100 | None = None
    model: Str100 | None = None
    purchase_date: date | None = None
    warranty_end: date | None = None
    cost: Cost | None = None
    location: Str100 | None = None
    notes: Notes | None = None


class StatusChange(StrictModel):
    """Body for POST /api/assets/{id}/status."""

    new_status: AssetStatus
    employee_id: int | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    # The operator confirms the device was wiped. This records the action only;
    # the application never erases a device itself.
    wipe_confirmed: bool = False


MAC_PATTERN = r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"
PHONE_PATTERN = r"^[0-9+\-() ]{6,20}$"

MacAddress = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MAC_PATTERN)]
Imei = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{14,16}$")]
PhoneNumber = Annotated[str, StringConstraints(strip_whitespace=True, pattern=PHONE_PATTERN)]
SimIccid = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{18,22}$")]


class DeviceDetailUpdate(PartialUpdate):
    """Body for PUT /api/assets/{id}/details. Every text field can be cleared with null."""

    NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {
            "os",
            "os_version",
            "cpu",
            "ram_gb",
            "storage_gb",
            "mac_address",
            "imei",
            "phone_number",
            "carrier",
            "sim_iccid",
            "last_check_in",
        }
    )

    os: Str50 | None = None
    os_version: Str50 | None = None
    cpu: Str100 | None = None
    ram_gb: Annotated[int, Field(ge=0, le=4096)] | None = None
    storage_gb: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    mac_address: MacAddress | None = None
    imei: Imei | None = None
    phone_number: PhoneNumber | None = None
    carrier: Str50 | None = None
    sim_iccid: SimIccid | None = None
    autopilot_registered: bool | None = None
    mdm_enrolled: bool | None = None
    encryption_on: bool | None = None
    compliance: Compliance | None = None
    last_check_in: datetime | None = None


class HolderSummary(BaseModel):
    """The employee currently holding a device."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    name: str
    department: str


class DeviceDetailOut(BaseModel):
    """Technical details of a device. Autopilot and Intune values are entered manually."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: int
    os: str | None
    os_version: str | None
    cpu: str | None
    ram_gb: int | None
    storage_gb: int | None
    mac_address: str | None
    imei: str | None
    phone_number: str | None
    carrier: str | None
    sim_iccid: str | None
    autopilot_registered: bool
    mdm_enrolled: bool
    encryption_on: bool
    compliance: Compliance
    last_check_in: datetime | None
    updated_at: datetime


class AssetOut(BaseModel):
    """An asset in lists. os and compliance come from the device details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_tag: str
    type: AssetType
    serial_number: str
    manufacturer: str
    model: str
    purchase_date: date | None
    warranty_end: date | None
    cost: Decimal | None
    location: str | None
    status: AssetStatus
    notes: str | None
    holder: HolderSummary | None
    os: str | None = None
    compliance: Compliance | None = None
    created_at: datetime
    updated_at: datetime


class AssetDetailOut(AssetOut):
    """One asset with its details and the status changes allowed from here.

    allowed_transitions lets the device page show only valid buttons. The
    server still checks every change; the list is a convenience, not the rule.
    """

    details: DeviceDetailOut | None
    allowed_transitions: list[AssetStatus]


class HistoryEntry(BaseModel):
    """One audit event in a device's timeline."""

    id: int
    action: str
    actor_email: str | None
    detail: dict[str, Any]
    created_at: datetime
