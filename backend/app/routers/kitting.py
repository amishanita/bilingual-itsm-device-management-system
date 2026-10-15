"""Kitting endpoints: templates, starting a run, the device checklist, steps, and the board.

Writes and the board are it_admin or super_admin only. The device checklist is
readable by managers too, within their asset scope.
"""

from fastapi import APIRouter, Query

from app.core.deps import DbSession, ItAdmin, ManagerOrAdmin
from app.schemas.assets import AssetType
from app.schemas.kitting import (
    BoardGroup,
    ChecklistOut,
    KittingStart,
    TaskOut,
    TaskUpdate,
    TemplateCreate,
    TemplateOut,
)
from app.services import asset_service, kitting_service

router = APIRouter(tags=["kitting"])


@router.get("/kitting/templates", response_model=list[TemplateOut])
def list_templates(
    db: DbSession, _admin: ItAdmin, device_type: AssetType | None = None
) -> list[TemplateOut]:
    """All kitting templates, optionally for one device type."""
    return [TemplateOut.model_validate(t) for t in kitting_service.list_templates(db, device_type)]


@router.post("/kitting/templates", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateCreate, db: DbSession, admin: ItAdmin) -> TemplateOut:
    """Add a kitting template with steps in English and Japanese."""
    template = kitting_service.create_template(
        db, body.device_type, body.name, [step.model_dump() for step in body.steps], admin
    )
    db.commit()
    return TemplateOut.model_validate(template)


@router.post("/assets/{asset_id}/kitting/start", response_model=ChecklistOut, status_code=201)
def start_kitting(asset_id: int, body: KittingStart, db: DbSession, admin: ItAdmin) -> ChecklistOut:
    """Move an in_stock device to kitting and create its checklist from a template."""
    asset = kitting_service.start_kitting(db, asset_id, body.template_id, admin)
    db.commit()
    db.refresh(asset)
    return ChecklistOut(**kitting_service.checklist(db, asset))


@router.get("/assets/{asset_id}/kitting", response_model=ChecklistOut)
def read_checklist(
    asset_id: int,
    db: DbSession,
    user: ManagerOrAdmin,
    run_no: int | None = Query(default=None, ge=1),
) -> ChecklistOut:
    """A device's kitting checklist: the latest run, or an earlier one with ?run_no=."""
    asset = asset_service.get_visible_asset(db, asset_id, user)
    return ChecklistOut(**kitting_service.checklist(db, asset, run_no))


@router.patch("/kitting-tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: DbSession, admin: ItAdmin) -> TaskOut:
    """Tick or untick one step of a device's current kitting run."""
    task = kitting_service.set_task_done(db, task_id, body.done, admin)
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.get("/kitting/board", response_model=list[BoardGroup])
def kitting_board(db: DbSession, _admin: ItAdmin) -> list[BoardGroup]:
    """Devices in kitting with % done, grouped by who is working on them."""
    return [BoardGroup(**group) for group in kitting_service.board(db)]
