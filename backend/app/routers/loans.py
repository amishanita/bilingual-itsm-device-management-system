"""Loan endpoints.

GET is open to it_admin, super_admin, and managers (own department only, Part B.2).
Lending and returning are it_admin and super_admin only.
"""

from typing import Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.database import commit_or_conflict
from app.core.deps import DbSession, ItAdmin, ManagerOrAdmin
from app.models import Asset, DeviceLoan, Employee
from app.schemas.common import Limit, Offset, Page
from app.schemas.loans import LoanAsset, LoanCreate, LoanEmployee, LoanOut, LoanReturn
from app.services import loan_service

router = APIRouter(prefix="/loans", tags=["loans"])


def to_out(loan: DeviceLoan, asset: Asset, employee: Employee) -> LoanOut:
    """A loan with its device and borrower."""
    return LoanOut(
        id=loan.id,
        asset=LoanAsset(id=asset.id, asset_tag=asset.asset_tag, type=asset.type, model=asset.model),
        employee=LoanEmployee(
            id=employee.id,
            employee_code=employee.employee_code,
            name=employee.name,
            department=employee.department,
        ),
        lent_by=loan.lent_by,
        lent_at=loan.lent_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        condition=loan.condition,
        wipe_done=loan.wipe_done,
        note=loan.note,
        is_overdue=loan_service.is_overdue(loan, loan_service.now_utc()),
    )


def one_out(db: DbSession, loan: DeviceLoan) -> LoanOut:
    """Build the response for a single loan."""
    return to_out(loan, db.get(Asset, loan.asset_id), db.get(Employee, loan.employee_id))


@router.get("", response_model=Page[LoanOut])
def list_loans(
    db: DbSession,
    user: ManagerOrAdmin,
    overdue: bool | None = None,
    state: Literal["open", "returned"] | None = None,
    employee_id: int | None = None,
    asset_id: int | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[LoanOut]:
    """List loans. overdue=true keeps loans past their due date and not returned.

    Open loans come first, soonest due date first; returned loans follow, latest first.
    """
    now = loan_service.now_utc()
    query = loan_service.scope_loans(select(DeviceLoan), user)
    if overdue is not None:
        condition = loan_service.overdue_condition(now)
        query = query.where(condition if overdue else ~condition)
    if state == "open":
        query = query.where(DeviceLoan.returned_at.is_(None))
    elif state == "returned":
        query = query.where(DeviceLoan.returned_at.is_not(None))
    if employee_id is not None:
        query = query.where(DeviceLoan.employee_id == employee_id)
    if asset_id is not None:
        query = query.where(DeviceLoan.asset_id == asset_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    loans = db.scalars(
        query.order_by(
            DeviceLoan.returned_at.is_not(None),
            DeviceLoan.due_at,
            DeviceLoan.returned_at.desc(),
            DeviceLoan.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    # Two batched lookups for the whole page instead of two queries per loan.
    assets = {
        a.id: a for a in db.scalars(select(Asset).where(Asset.id.in_({x.asset_id for x in loans})))
    }
    employees = {
        e.id: e
        for e in db.scalars(select(Employee).where(Employee.id.in_({x.employee_id for x in loans})))
    }
    items = [to_out(x, assets[x.asset_id], employees[x.employee_id]) for x in loans]
    return Page[LoanOut](items=items, total=total)


@router.post("", response_model=LoanOut, status_code=201)
def create_loan(body: LoanCreate, db: DbSession, admin: ItAdmin) -> LoanOut:
    """Lend a ready device to an active employee until the due date."""
    loan = loan_service.lend(db, body.asset_id, body.employee_id, body.due_at, body.note, admin)
    commit_or_conflict(db)
    return one_out(db, loan)


@router.post("/{loan_id}/return", response_model=LoanOut)
def return_loan(loan_id: int, body: LoanReturn, db: DbSession, admin: ItAdmin) -> LoanOut:
    """Return a loaned device with its condition, optionally confirming a wipe."""
    loan = loan_service.return_loan(db, loan_id, body.condition, body.wipe_done, body.note, admin)
    db.commit()
    db.refresh(loan)
    return one_out(db, loan)
