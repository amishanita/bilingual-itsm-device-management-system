"""Schemas for kitting templates, checklists, and the kitting board."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.assets import AssetStatus, AssetType
from app.schemas.common import StrictModel

StepText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TemplateStep(StrictModel):
    """One checklist step in English and Japanese."""

    en: StepText
    ja: StepText


class TemplateCreate(StrictModel):
    """Body for POST /api/kitting/templates."""

    device_type: AssetType
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    steps: Annotated[list[TemplateStep], Field(min_length=1, max_length=50)]


class TemplateOut(BaseModel):
    """A kitting template."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_type: AssetType
    name: str
    steps: list[TemplateStep]
    created_at: datetime


class KittingStart(StrictModel):
    """Body for POST /api/assets/{id}/kitting/start.

    template_id may be left out when the device type has exactly one template.
    """

    template_id: int | None = None


class TaskUpdate(StrictModel):
    """Body for PATCH /api/kitting-tasks/{id}: tick (true) or untick (false)."""

    done: bool


class TaskOut(BaseModel):
    """One checklist step. The frontend shows step_ja or step_en by language."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_no: int
    step_no: int
    step_en: str
    step_ja: str
    done: bool
    done_by: int | None
    done_at: datetime | None


class ChecklistOut(BaseModel):
    """One kitting run of a device. runs lists every run, so history can be browsed."""

    asset_id: int
    status: AssetStatus
    run_no: int | None
    runs: list[int]
    editable: bool
    done: int
    total: int
    percent: int
    tasks: list[TaskOut]


class BoardDevice(BaseModel):
    """A device on the kitting board."""

    asset_id: int
    asset_tag: str
    type: AssetType
    model: str
    run_no: int | None
    done: int
    total: int
    percent: int


class BoardWorker(BaseModel):
    """The IT staff member a group of devices belongs to."""

    id: int
    email: str | None


class BoardGroup(BaseModel):
    """Devices grouped by who is working on them. worker is null for unassigned."""

    worker: BoardWorker | None
    devices: list[BoardDevice]
