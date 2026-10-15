"""Schemas for device loans and the leaver's device list."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, StringConstraints

from app.schemas.assets import AssetOut, AssetType
from app.schemas.common import StrictModel

LoanCondition = Literal["ok", "damaged", "missing_parts"]
LoanNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class LoanCreate(StrictModel):
    """Body for POST /api/loans.

    due_at must carry a timezone (for example 2026-10-30T18:00:00+09:00), so it
    is stored in UTC without guessing what local time was meant.
    """

    asset_id: int
    employee_id: int
    due_at: AwareDatetime
    note: LoanNote | None = None


class LoanReturn(StrictModel):
    """Body for POST /api/loans/{id}/return. condition is required."""

    condition: LoanCondition
    wipe_done: bool = False
    note: LoanNote | None = None


class LoanAsset(BaseModel):
    """The device on loan."""

    id: int
    asset_tag: str
    type: AssetType
    model: str


class LoanEmployee(BaseModel):
    """The borrower."""

    id: int
    employee_code: str
    name: str
    department: str


class LoanOut(BaseModel):
    """A loan with its device, borrower, and overdue flag."""

    id: int
    asset: LoanAsset
    employee: LoanEmployee
    lent_by: int
    lent_at: datetime
    due_at: datetime
    returned_at: datetime | None
    condition: LoanCondition | None
    wipe_done: bool
    note: str | None
    is_overdue: bool


class OpenLoanSummary(BaseModel):
    """The open loan behind an on_loan device, so the leaver page can offer a return."""

    id: int
    due_at: datetime
    is_overdue: bool


class HeldDeviceOut(AssetOut):
    """A device an employee currently holds (assigned, on loan, or in repair)."""

    open_loan: OpenLoanSummary | None = None
