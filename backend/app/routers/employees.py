"""Employee records.

Read: manager (own department only), it_admin, super_admin.
Write: it_admin, super_admin. DELETE marks the employee as "left"; nothing is erased.
"""

from fastapi import APIRouter
from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import AppEnv
from app.core.database import commit_or_conflict
from app.core.demo import is_demo_account
from app.core.deps import AppSettings, DbSession, ItAdmin, ManagerOrAdmin, manager_department
from app.core.errors import AppError
from app.models import Employee, User
from app.schemas.common import Limit, Offset, Page, SearchText, like_pattern
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeStatus,
    EmployeeUpdate,
)
from app.services import audit_service

router = APIRouter(prefix="/employees", tags=["employees"])


def scope_employees(query: Select[tuple[Employee]], user: User) -> Select[tuple[Employee]]:
    """Restrict an employee query to what the caller may see.

    Managers see their own department only. The filter is part of the SQL
    query, so out-of-scope rows are never loaded. A manager with no linked
    employee matches nothing.
    """
    if user.role != "manager":
        return query
    department = manager_department(user)
    if department is None:
        return query.where(false())
    return query.where(Employee.department == department)


def get_visible_employee(db: Session, employee_id: int, user: User) -> Employee:
    """Load one employee the caller may see, or raise 404.

    Out-of-scope records also give 404, so a manager cannot probe which
    employee IDs exist in other departments.
    """
    query = scope_employees(select(Employee).where(Employee.id == employee_id), user)
    employee = db.scalar(query)
    if employee is None:
        raise AppError(404, "EMPLOYEE_NOT_FOUND", "The employee does not exist.")
    return employee


def check_unique(
    db: Session, code: str | None, email: str | None, exclude_id: int | None = None
) -> None:
    """Refuse a duplicate employee code or email with a specific error code."""
    for column, value, error_code, label in (
        (Employee.employee_code, code, "EMPLOYEE_CODE_EXISTS", "employee code"),
        (Employee.email, email, "EMAIL_ALREADY_EXISTS", "email"),
    ):
        if value is None:
            continue
        query = select(Employee.id).where(column == value)
        if exclude_id is not None:
            query = query.where(Employee.id != exclude_id)
        if db.scalar(query) is not None:
            raise AppError(400, error_code, f"An employee with this {label} already exists.")


@router.get("", response_model=Page[EmployeeOut])
def list_employees(
    db: DbSession,
    user: ManagerOrAdmin,
    q: SearchText = None,
    department: str | None = None,
    status: EmployeeStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[EmployeeOut]:
    """List employees. q searches name, employee code, and email."""
    query = scope_employees(select(Employee), user)
    if q:
        pattern = like_pattern(q)
        query = query.where(
            or_(
                Employee.name.ilike(pattern, escape="\\"),
                Employee.employee_code.ilike(pattern, escape="\\"),
                Employee.email.ilike(pattern, escape="\\"),
            )
        )
    if department:
        query = query.where(Employee.department == department)
    if status:
        query = query.where(Employee.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Employee.employee_code).limit(limit).offset(offset)).all()
    return Page[EmployeeOut](items=[EmployeeOut.model_validate(e) for e in rows], total=total)


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeCreate, db: DbSession, admin: ItAdmin) -> EmployeeOut:
    """Add an employee record."""
    check_unique(db, body.employee_code, body.email)
    employee = Employee(**body.model_dump())
    db.add(employee)
    db.flush()
    audit_service.record(
        db,
        admin,
        "EMPLOYEE_CREATED",
        "employee",
        employee.id,
        {"employee_code": employee.employee_code, "department": employee.department},
    )
    commit_or_conflict(db)
    return EmployeeOut.model_validate(employee)


@router.get("/{employee_id}", response_model=EmployeeOut)
def read_employee(employee_id: int, db: DbSession, user: ManagerOrAdmin) -> EmployeeOut:
    """Return one employee within the caller's scope."""
    return EmployeeOut.model_validate(get_visible_employee(db, employee_id, user))


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: int, body: EmployeeUpdate, db: DbSession, admin: ItAdmin
) -> EmployeeOut:
    """Update employee fields. Only the fields sent are changed."""
    employee = get_visible_employee(db, employee_id, admin)
    changes = body.changes()
    check_unique(db, body.employee_code, body.email, exclude_id=employee.id)

    audit_detail: dict[str, object] = {}
    for field, value in changes.items():
        old = getattr(employee, field)
        if value != old:
            # Dates are stored in the audit log as ISO strings so the JSON stays plain.
            audit_detail[field] = {"old": str(old), "new": str(value)}
            setattr(employee, field, value)

    if audit_detail:
        audit_service.record(db, admin, "EMPLOYEE_UPDATED", "employee", employee.id, audit_detail)
        commit_or_conflict(db)
        db.refresh(employee)
    return EmployeeOut.model_validate(employee)


@router.delete("/{employee_id}", response_model=EmployeeOut)
def mark_employee_left(
    employee_id: int, db: DbSession, admin: ItAdmin, settings: AppSettings
) -> EmployeeOut:
    """Leaver flow, step 1: set status to "left" and deactivate the linked login.

    The record, its devices, loans, tickets, and audit history all stay.
    Devices are not returned and tickets are not closed automatically; IT
    returns each device explicitly from the employee page.
    """
    employee = get_visible_employee(db, employee_id, admin)
    if employee.status == "left":
        raise AppError(400, "EMPLOYEE_ALREADY_LEFT", "This employee is already marked as left.")

    login = db.scalar(select(User).where(User.employee_id == employee.id))
    if login is not None and settings.app_env == AppEnv.DEMO and is_demo_account(login.email):
        raise AppError(403, "DEMO_ACCOUNT_LOCKED", "Demo accounts cannot be changed.")

    old_status = employee.status
    employee.status = "left"
    deactivated_login = None
    # A leaver must not keep access to company data through their own login.
    if login is not None and login.is_active:
        login.is_active = False
        deactivated_login = login.id

    audit_service.record(
        db,
        admin,
        "EMPLOYEE_LEFT",
        "employee",
        employee.id,
        {"old_status": old_status, "login_deactivated": deactivated_login},
    )
    db.commit()
    db.refresh(employee)
    return EmployeeOut.model_validate(employee)
