"""Schemas for employee records."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import Email, PartialUpdate, StrictModel

EmployeeStatus = Literal["active", "on_leave", "left"]
# "left" is set only through DELETE (the leaver flow), never by create or update.
EditableStatus = Literal["active", "on_leave"]

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class EmployeeCreate(StrictModel):
    """Body for POST /api/employees."""

    employee_code: Code
    name: Text100
    email: Email
    department: Text100
    position: Text100
    join_date: date
    status: EditableStatus = "active"


class EmployeeUpdate(PartialUpdate):
    """Body for PUT /api/employees/{id}. Every field is optional.

    Setting status back to active re-activates a former leaver (rehire).
    """

    employee_code: Code | None = None
    name: Text100 | None = None
    email: Email | None = None
    department: Text100 | None = None
    position: Text100 | None = None
    join_date: date | None = None
    status: EditableStatus | None = None


class EmployeeOut(BaseModel):
    """An employee record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    name: str
    email: str
    department: str
    position: str
    join_date: date
    status: EmployeeStatus
    created_at: datetime
    updated_at: datetime
