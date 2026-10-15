"""Asset lifecycle, asset changes, and who may see which assets.

Every status change goes through change_status(). Routers never set
asset.status or asset.assigned_to themselves.

Functions here add changes and audit rows to the session but do not commit.
The caller commits once, so a business change and its audit record always
succeed or fail together, and other services (kitting, loans) can combine
several steps into one transaction.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, exists, false, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import Asset, AuditLog, DeviceDetail, DeviceLoan, Employee, KittingTask, User
from app.models.base import HELD_ASSET_STATUSES
from app.services import audit_service

# Forward moves of the lifecycle. Anything not listed is rejected with
# INVALID_STATUS_CHANGE.
_FORWARD: dict[str, frozenset[str]] = {
    "ordered": frozenset({"in_stock"}),
    "in_stock": frozenset({"kitting"}),
    "kitting": frozenset({"ready"}),
    "ready": frozenset({"assigned", "on_loan"}),
    "assigned": frozenset({"returned", "repair"}),
    "on_loan": frozenset({"returned"}),
    "returned": frozenset({"wiped"}),
    "wiped": frozenset({"in_stock"}),
    "repair": frozenset({"ready"}),
    "retired": frozenset(),
}

# Every status except retired may also move to retired. Retired is final:
# a retired asset never re-enters the lifecycle.
TRANSITIONS: dict[str, frozenset[str]] = {
    status: (targets if status == "retired" else targets | {"retired"})
    for status, targets in _FORWARD.items()
}

# Moves that must create or close related records, and so belong to a
# dedicated workflow instead of the plain status endpoint:
# - kitting: starting kitting copies a template into the device's checklist
# - loan: lending and returning create or close a loan with a due date and condition
WORKFLOW_TRANSITIONS: dict[tuple[str, str], str] = {
    ("in_stock", "kitting"): "kitting",
    ("ready", "on_loan"): "loan",
    ("on_loan", "returned"): "loan",
}
WORKFLOW_ERRORS = {
    "kitting": ("KITTING_WORKFLOW_REQUIRED", "Start kitting through the kitting endpoint."),
    "loan": (
        "LOAN_WORKFLOW_REQUIRED",
        "Lending and loan returns must go through the loans endpoints.",
    ),
}

# Statuses reached by handing the device to an employee.
HANDOVER_STATUSES = frozenset({"assigned", "on_loan"})


# Reading and scoping


def scope_assets(query: Select[tuple[Asset]], user: User) -> Select[tuple[Asset]]:
    """Restrict an asset query to what the caller may see.

    - it_admin, super_admin: everything.
    - manager: devices held (assigned, on loan, or in repair) by employees of
      their own department (Part B.2). Stock and unheld devices are hidden.
    - employee: only devices they hold themselves (read-only).
    The filter is part of the SQL query, so out-of-scope rows are never loaded.
    """
    if user.role in ("it_admin", "super_admin"):
        return query
    if user.role == "manager":
        if user.employee is None:
            return query.where(false())
        held_in_department = select(Employee.id).where(
            Employee.department == user.employee.department
        )
        return query.where(
            Asset.status.in_(HELD_ASSET_STATUSES), Asset.assigned_to.in_(held_in_department)
        )
    if user.role == "employee" and user.employee_id is not None:
        return query.where(Asset.assigned_to == user.employee_id)
    return query.where(false())


def get_visible_asset(db: Session, asset_id: int, user: User) -> Asset:
    """Load one asset the caller may see, or raise 404.

    Out-of-scope assets give the same 404 as missing ones, so IDs cannot be probed.
    """
    query = scope_assets(select(Asset).where(Asset.id == asset_id), user)
    asset = db.scalar(query.options(selectinload(Asset.holder)))
    if asset is None:
        raise AppError(404, "ASSET_NOT_FOUND", "The asset does not exist.")
    return asset


def lock_asset(db: Session, asset_id: int) -> Asset:
    """Load an asset with a row lock (SELECT ... FOR UPDATE), or raise 404.

    Two requests changing the same asset are serialized: the second waits,
    then sees the first one's result. This prevents a device from being
    assigned twice by simultaneous requests.
    """
    asset = db.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise AppError(404, "ASSET_NOT_FOUND", "The asset does not exist.")
    return asset


def allowed_transitions(asset: Asset) -> list[str]:
    """Statuses this asset may move to next, in lifecycle order."""
    targets = TRANSITIONS[asset.status]
    return [status for status in TRANSITIONS if status in targets]


def asset_history(db: Session, asset_id: int) -> list[dict[str, Any]]:
    """The audit timeline of one asset, oldest first, with the actor's email."""
    rows = db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.entity == "asset", AuditLog.entity_id == asset_id)
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()
    return [
        {
            "id": entry.id,
            "action": entry.action,
            "actor_email": email,
            "detail": entry.detail,
            "created_at": entry.created_at,
        }
        for entry, email in rows
    ]


# Lifecycle


def invalid_change(current: str, requested: str) -> AppError:
    """The standard error for a transition the lifecycle does not allow."""
    return AppError(
        400,
        "INVALID_STATUS_CHANGE",
        f"An asset cannot move from {current} to {requested}.",
    )


def check_kitting_complete(db: Session, asset: Asset) -> None:
    """Allow kitting -> ready only when every step of the latest kitting run is done.

    A device with no kitting steps at all has not been kitted, so it is
    treated as incomplete too.
    """
    not_complete = AppError(
        400, "KITTING_NOT_COMPLETE", "All kitting steps must be completed before ready."
    )
    latest_run = db.scalar(
        select(func.max(KittingTask.run_no)).where(KittingTask.asset_id == asset.id)
    )
    if latest_run is None:
        raise not_complete
    open_steps = db.scalar(
        select(func.count())
        .select_from(KittingTask)
        .where(
            KittingTask.asset_id == asset.id,
            KittingTask.run_no == latest_run,
            KittingTask.done.is_(False),
        )
    )
    if open_steps:
        raise not_complete


def load_active_employee(db: Session, employee_id: int | None) -> Employee:
    """A device can only be handed to an existing employee whose status is active."""
    if employee_id is None:
        raise AppError(400, "EMPLOYEE_REQUIRED", "An employee is required for this change.")
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError(400, "EMPLOYEE_NOT_FOUND", "The employee does not exist.")
    if employee.status != "active":
        raise AppError(400, "EMPLOYEE_NOT_ACTIVE", "The employee is not active.")
    return employee


def has_open_loan(db: Session, asset_id: int) -> bool:
    """True if the asset has a loan that has not been returned yet."""
    return bool(
        db.scalar(
            select(
                exists().where(DeviceLoan.asset_id == asset_id, DeviceLoan.returned_at.is_(None))
            )
        )
    )


def change_status(
    db: Session,
    asset_id: int,
    new_status: str,
    actor: User,
    *,
    employee_id: int | None = None,
    note: str | None = None,
    wipe_confirmed: bool = False,
    workflow: str | None = None,
) -> Asset:
    """Move an asset to a new lifecycle status after checking every rule.

    The asset row is locked first, so the rules are checked against its
    latest state. Raises AppError (400) for any rule violation; nothing is
    changed in that case. workflow is set only by the kitting and loan
    services, for the moves they own (WORKFLOW_TRANSITIONS).
    """
    asset = lock_asset(db, asset_id)
    current = asset.status

    if new_status == current or new_status not in TRANSITIONS[current]:
        raise invalid_change(current, new_status)
    required_workflow = WORKFLOW_TRANSITIONS.get((current, new_status))
    if required_workflow is not None and workflow != required_workflow:
        code, message = WORKFLOW_ERRORS[required_workflow]
        raise AppError(400, code, message)
    if employee_id is not None and new_status not in HANDOVER_STATUSES:
        raise AppError(400, "EMPLOYEE_NOT_ALLOWED", "An employee is only used when handing over.")

    if current == "kitting" and new_status == "ready":
        check_kitting_complete(db, asset)
    if new_status in HANDOVER_STATUSES:
        employee = load_active_employee(db, employee_id)
    if new_status == "wiped" and not wipe_confirmed:
        raise AppError(400, "WIPE_CONFIRMATION_REQUIRED", "Confirm that the device has been wiped.")
    if new_status == "retired":
        if not note:
            raise AppError(
                400,
                "RETIREMENT_NOTE_REQUIRED",
                "Retirement needs a disposal record or erase certificate number.",
            )
        if has_open_loan(db, asset.id):
            raise AppError(
                400, "OPEN_LOAN_EXISTS", "Close the open loan before retiring this device."
            )

    previous_holder = asset.assigned_to
    asset.status = new_status
    # Holder rules: set on handover, kept during repair, cleared everywhere else.
    if new_status in HANDOVER_STATUSES:
        asset.assigned_to = employee.id
    elif new_status != "repair":
        asset.assigned_to = None
    if new_status == "retired":
        stamp = datetime.now(UTC).date().isoformat()
        asset.notes = f"{asset.notes}\n" if asset.notes else ""
        asset.notes += f"[{stamp} retired] {note}"

    detail: dict[str, Any] = {"old_status": current, "new_status": new_status}
    if asset.assigned_to is not None:
        detail["employee_id"] = asset.assigned_to
    elif previous_holder is not None:
        detail["previous_employee_id"] = previous_holder
    if note:
        detail["note"] = note
    if new_status == "wiped":
        detail["wipe_confirmed"] = True
    action = {"assigned": "ASSET_ASSIGNED", "retired": "ASSET_RETIRED"}.get(
        new_status, "ASSET_STATUS_CHANGED"
    )
    audit_service.record(db, actor, action, "asset", asset.id, detail)
    db.flush()
    return asset


# Creating and editing


def check_unique_asset(
    db: Session, asset_tag: str | None, serial: str | None, exclude_id: int | None = None
) -> None:
    """Refuse a duplicate asset tag or serial number with a specific error code."""
    for column, value, code, label in (
        (Asset.asset_tag, asset_tag, "ASSET_TAG_EXISTS", "asset tag"),
        (Asset.serial_number, serial, "SERIAL_NUMBER_EXISTS", "serial number"),
    ):
        if value is None:
            continue
        query = select(Asset.id).where(column == value)
        if exclude_id is not None:
            query = query.where(Asset.id != exclude_id)
        if db.scalar(query) is not None:
            raise AppError(400, code, f"An asset with this {label} already exists.")


def create_asset(db: Session, values: dict[str, Any], actor: User) -> Asset:
    """Create an asset together with an empty device-details row."""
    check_unique_asset(db, values["asset_tag"], values["serial_number"])
    asset = Asset(**values)
    db.add(asset)
    db.flush()
    db.add(DeviceDetail(asset_id=asset.id))
    audit_service.record(
        db,
        actor,
        "ASSET_CREATED",
        "asset",
        asset.id,
        {"asset_tag": asset.asset_tag, "type": asset.type, "status": asset.status},
    )
    db.flush()
    return asset


def apply_changes(target: object, changes: dict[str, Any]) -> dict[str, Any]:
    """Set changed attributes and return an audit-friendly {field: {old, new}} map.

    Values are stored as strings so dates, decimals, and datetimes stay plain JSON.
    """
    diff: dict[str, Any] = {}
    for field, value in changes.items():
        old = getattr(target, field)
        if value != old:
            diff[field] = {
                "old": None if old is None else str(old),
                "new": None if value is None else str(value),
            }
            setattr(target, field, value)
    return diff


def update_asset(db: Session, asset_id: int, changes: dict[str, Any], actor: User) -> Asset:
    """Update descriptive asset fields. Status and holder are not editable here."""
    asset = lock_asset(db, asset_id)
    check_unique_asset(
        db, changes.get("asset_tag"), changes.get("serial_number"), exclude_id=asset.id
    )
    # The combined result must still respect the warranty rule.
    purchase = changes.get("purchase_date", asset.purchase_date)
    warranty = changes.get("warranty_end", asset.warranty_end)
    if purchase and warranty and warranty < purchase:
        raise AppError(
            400, "WARRANTY_BEFORE_PURCHASE", "The warranty cannot end before the purchase date."
        )
    diff = apply_changes(asset, changes)
    if diff:
        audit_service.record(db, actor, "ASSET_UPDATED", "asset", asset.id, diff)
        db.flush()
    return asset


def get_details(db: Session, asset: Asset) -> DeviceDetail:
    """Return the asset's details row, creating an empty one if it is missing."""
    details = db.get(DeviceDetail, asset.id)
    if details is None:
        details = DeviceDetail(asset_id=asset.id)
        db.add(details)
        db.flush()
    return details


def update_details(
    db: Session, asset_id: int, changes: dict[str, Any], actor: User
) -> DeviceDetail:
    """Update technical details. Audited under the asset so it shows in its history."""
    asset = lock_asset(db, asset_id)
    details = get_details(db, asset)
    diff = apply_changes(details, changes)
    if diff:
        audit_service.record(db, actor, "DEVICE_DETAILS_UPDATED", "asset", asset.id, diff)
        db.flush()
    return details
