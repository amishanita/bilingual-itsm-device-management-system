"""Device loans: lending, returning, overdue logic, and who may see which loans.

Lending and returning both change the device's lifecycle status, so they go
through asset_service.change_status with workflow="loan". The loan record,
the status changes, and their audit rows are one transaction.

Like the other services, these functions do not commit; the router commits once.
"""

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, Select, and_, false, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import DeviceLoan, Employee, User
from app.services import asset_service, audit_service


def now_utc() -> datetime:
    """The current time in UTC. One place, so tests and rules agree on "now"."""
    return datetime.now(UTC)


def overdue_condition(now: datetime) -> ColumnElement[bool]:
    """SQL condition for an overdue loan: due date passed and not returned."""
    return and_(DeviceLoan.returned_at.is_(None), DeviceLoan.due_at < now)


def is_overdue(loan: DeviceLoan, now: datetime) -> bool:
    """The same rule as overdue_condition, for a loaded loan."""
    return loan.returned_at is None and loan.due_at < now


def scope_loans(query: Select[tuple[DeviceLoan]], user: User) -> Select[tuple[DeviceLoan]]:
    """Restrict a loan query to what the caller may see.

    it_admin and super_admin see all loans. A manager sees loans of employees
    in their own department (Part B.2), filtered in SQL. Everyone else sees none.
    """
    if user.role in ("it_admin", "super_admin"):
        return query
    if user.role == "manager" and user.employee is not None:
        in_department = select(Employee.id).where(Employee.department == user.employee.department)
        return query.where(DeviceLoan.employee_id.in_(in_department))
    return query.where(false())


def lock_loan(db: Session, loan_id: int) -> DeviceLoan:
    """Load a loan with a row lock, so two returns of the same loan cannot both succeed."""
    loan = db.scalar(select(DeviceLoan).where(DeviceLoan.id == loan_id).with_for_update())
    if loan is None:
        raise AppError(404, "LOAN_NOT_FOUND", "The loan does not exist.")
    return loan


def lend(
    db: Session,
    asset_id: int,
    employee_id: int,
    due_at: datetime,
    note: str | None,
    actor: User,
) -> DeviceLoan:
    """Lend a ready device to an active employee until due_at.

    The lifecycle service checks the device is ready and the employee is active,
    locks the device, sets the holder, and audits ready -> on_loan.
    """
    now = now_utc()
    if due_at <= now:
        raise AppError(400, "DUE_DATE_IN_PAST", "The due date must be in the future.")

    asset_service.change_status(
        db, asset_id, "on_loan", actor, employee_id=employee_id, note=note, workflow="loan"
    )
    loan = DeviceLoan(
        asset_id=asset_id,
        employee_id=employee_id,
        lent_by=actor.id,
        lent_at=now,
        due_at=due_at,
        note=note,
    )
    db.add(loan)
    db.flush()
    audit_service.record(
        db,
        actor,
        "LOAN_CREATED",
        "loan",
        loan.id,
        {"asset_id": asset_id, "employee_id": employee_id, "due_at": due_at.isoformat()},
    )
    db.flush()
    return loan


def return_loan(
    db: Session,
    loan_id: int,
    condition: str,
    wipe_done: bool,
    note: str | None,
    actor: User,
) -> DeviceLoan:
    """Close a loan and take the device back.

    Without wipe confirmation the device goes to returned. With it, the device
    goes on to wiped. Wipe confirmation records what the operator did; the
    application does not erase the device. A loan can be returned only once.
    """
    loan = lock_loan(db, loan_id)
    if loan.returned_at is not None:
        raise AppError(400, "LOAN_ALREADY_RETURNED", "This loan has already been returned.")

    asset_service.change_status(db, loan.asset_id, "returned", actor, workflow="loan")
    if wipe_done:
        asset_service.change_status(db, loan.asset_id, "wiped", actor, wipe_confirmed=True)

    loan.returned_at = now_utc()
    loan.condition = condition
    loan.wipe_done = wipe_done
    if note:
        loan.note = f"{loan.note}\n{note}" if loan.note else note
    audit_service.record(
        db,
        actor,
        "LOAN_RETURNED",
        "loan",
        loan.id,
        {"asset_id": loan.asset_id, "condition": condition, "wipe_done": wipe_done},
    )
    db.flush()
    return loan
