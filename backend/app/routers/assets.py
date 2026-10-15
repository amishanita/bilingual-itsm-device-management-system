"""Asset endpoints: list, create, edit, device details, lifecycle status, and history.

Read access is scoped per role by asset_service.scope_assets. Every write is
it_admin or super_admin only, and every status change goes through the
lifecycle service.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.database import commit_or_conflict
from app.core.deps import ADMIN_ROLES, CurrentUser, DbSession, ItAdmin, ManagerOrAdmin
from app.models import Asset, DeviceDetail, DeviceLoan, Employee, User
from app.schemas.assets import (
    AssetCreate,
    AssetDetailOut,
    AssetOut,
    AssetStatus,
    AssetType,
    AssetUpdate,
    Compliance,
    DeviceDetailOut,
    DeviceDetailUpdate,
    HistoryEntry,
    StatusChange,
)
from app.schemas.common import Limit, Offset, Page, SearchText, like_pattern
from app.services import asset_service

router = APIRouter(prefix="/assets", tags=["assets"])


def to_out(asset: Asset, details: DeviceDetail | None) -> AssetOut:
    """List view of an asset, with os and compliance pulled from its details."""
    out = AssetOut.model_validate(asset)
    if details is not None:
        out.os = details.os
        out.compliance = details.compliance
    return out


def to_detail_out(db: DbSession, asset: Asset, user: User) -> AssetDetailOut:
    """Full view of one asset. Transitions are listed only for users who may change status."""
    details = asset_service.get_details(db, asset)
    base = to_out(asset, details).model_dump()
    return AssetDetailOut(
        **base,
        details=DeviceDetailOut.model_validate(details),
        allowed_transitions=(
            asset_service.allowed_transitions(asset) if user.role in ADMIN_ROLES else []
        ),
    )


@router.get("", response_model=Page[AssetOut])
def list_assets(
    db: DbSession,
    user: CurrentUser,
    type: AssetType | None = None,
    status: AssetStatus | None = None,
    os: str | None = None,
    compliance: Compliance | None = None,
    department: str | None = None,
    overdue: bool | None = None,
    q: SearchText = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[AssetOut]:
    """List assets the caller may see.

    q searches asset tag, serial number, model, IMEI, phone number, and the
    holder's name. department filters by the holder's department. overdue=true
    keeps devices with an open loan past its due date.
    """
    query = (
        select(Asset)
        .outerjoin(DeviceDetail, DeviceDetail.asset_id == Asset.id)
        .outerjoin(Employee, Employee.id == Asset.assigned_to)
    )
    query = asset_service.scope_assets(query, user)
    if type:
        query = query.where(Asset.type == type)
    if status:
        query = query.where(Asset.status == status)
    if os:
        query = query.where(DeviceDetail.os == os)
    if compliance:
        query = query.where(DeviceDetail.compliance == compliance)
    if department:
        query = query.where(Employee.department == department)
    if overdue is not None:
        open_overdue_loan = exists().where(
            DeviceLoan.asset_id == Asset.id,
            DeviceLoan.returned_at.is_(None),
            DeviceLoan.due_at < datetime.now(UTC),
        )
        query = query.where(open_overdue_loan if overdue else ~open_overdue_loan)
    if q:
        pattern = like_pattern(q)
        query = query.where(
            or_(
                Asset.asset_tag.ilike(pattern, escape="\\"),
                Asset.serial_number.ilike(pattern, escape="\\"),
                Asset.model.ilike(pattern, escape="\\"),
                DeviceDetail.imei.ilike(pattern, escape="\\"),
                DeviceDetail.phone_number.ilike(pattern, escape="\\"),
                Employee.name.ilike(pattern, escape="\\"),
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    assets = db.scalars(
        query.options(selectinload(Asset.holder))
        .order_by(Asset.asset_tag)
        .limit(limit)
        .offset(offset)
    ).all()
    details = {
        d.asset_id: d
        for d in db.scalars(
            select(DeviceDetail).where(DeviceDetail.asset_id.in_([a.id for a in assets]))
        )
    }
    return Page[AssetOut](items=[to_out(a, details.get(a.id)) for a in assets], total=total)


@router.post("", response_model=AssetDetailOut, status_code=201)
def create_asset(body: AssetCreate, db: DbSession, admin: ItAdmin) -> AssetDetailOut:
    """Register a new device, on order or in stock."""
    asset = asset_service.create_asset(db, body.model_dump(), admin)
    commit_or_conflict(db)
    return to_detail_out(db, asset, admin)


@router.get("/{asset_id}", response_model=AssetDetailOut)
def read_asset(asset_id: int, db: DbSession, user: CurrentUser) -> AssetDetailOut:
    """One asset with its details and allowed next statuses."""
    return to_detail_out(db, asset_service.get_visible_asset(db, asset_id, user), user)


@router.put("/{asset_id}", response_model=AssetDetailOut)
def update_asset(asset_id: int, body: AssetUpdate, db: DbSession, admin: ItAdmin) -> AssetDetailOut:
    """Edit descriptive fields. Use the status endpoint for lifecycle changes."""
    asset = asset_service.update_asset(db, asset_id, body.changes(), admin)
    commit_or_conflict(db)
    db.refresh(asset)
    return to_detail_out(db, asset, admin)


@router.get("/{asset_id}/details", response_model=DeviceDetailOut)
def read_details(asset_id: int, db: DbSession, user: CurrentUser) -> DeviceDetailOut:
    """Technical details of one asset."""
    asset = asset_service.get_visible_asset(db, asset_id, user)
    return DeviceDetailOut.model_validate(asset_service.get_details(db, asset))


@router.put("/{asset_id}/details", response_model=DeviceDetailOut)
def update_details(
    asset_id: int, body: DeviceDetailUpdate, db: DbSession, admin: ItAdmin
) -> DeviceDetailOut:
    """Update technical details. Autopilot and Intune fields are recorded manually."""
    details = asset_service.update_details(db, asset_id, body.changes(), admin)
    db.commit()
    db.refresh(details)
    return DeviceDetailOut.model_validate(details)


@router.post("/{asset_id}/status", response_model=AssetDetailOut)
def change_status(
    asset_id: int, body: StatusChange, db: DbSession, admin: ItAdmin
) -> AssetDetailOut:
    """Move the asset to its next lifecycle status.

    Rule violations return 400 with INVALID_STATUS_CHANGE, KITTING_NOT_COMPLETE,
    EMPLOYEE_REQUIRED, EMPLOYEE_NOT_ACTIVE, WIPE_CONFIRMATION_REQUIRED,
    RETIREMENT_NOTE_REQUIRED, OPEN_LOAN_EXISTS, KITTING_WORKFLOW_REQUIRED, or
    LOAN_WORKFLOW_REQUIRED.
    """
    asset = asset_service.change_status(
        db,
        asset_id,
        body.new_status,
        admin,
        employee_id=body.employee_id,
        note=body.note,
        wipe_confirmed=body.wipe_confirmed,
    )
    db.commit()
    db.refresh(asset)
    return to_detail_out(db, asset, admin)


@router.get("/{asset_id}/history", response_model=list[HistoryEntry])
def read_history(asset_id: int, db: DbSession, user: ManagerOrAdmin) -> list[HistoryEntry]:
    """The audit timeline of one asset, oldest first. Not available to employees."""
    asset = asset_service.get_visible_asset(db, asset_id, user)
    return [HistoryEntry(**entry) for entry in asset_service.asset_history(db, asset.id)]
