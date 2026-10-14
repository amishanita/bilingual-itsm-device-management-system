"""Login account management. Every endpoint here is super_admin only."""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import AppEnv, Settings
from app.core.database import commit_or_conflict
from app.core.demo import is_demo_account
from app.core.deps import AppSettings, DbSession, SuperAdmin
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import Employee, User
from app.schemas.common import Limit, Offset, Page, SearchText, like_pattern
from app.schemas.users import Role, UserCreate, UserOut, UserUpdate
from app.services import audit_service

router = APIRouter(prefix="/users", tags=["users"])


def get_linkable_employee(db: Session, employee_id: int, user_id: int | None) -> Employee:
    """Load an employee that a login may be linked to.

    The employee must exist, must not have left, and must not already belong
    to another login.
    """
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError(400, "EMPLOYEE_NOT_FOUND", "The employee does not exist.")
    if employee.status == "left":
        raise AppError(400, "EMPLOYEE_HAS_LEFT", "A login cannot be linked to a leaver.")
    holder = db.scalar(select(User.id).where(User.employee_id == employee_id))
    if holder is not None and holder != user_id:
        raise AppError(
            400, "EMPLOYEE_ALREADY_LINKED", "This employee is already linked to another login."
        )
    return employee


def check_not_demo_account(user: User, settings: Settings) -> None:
    """In demo mode the shared demo logins cannot be changed (Part B.1)."""
    if settings.app_env == AppEnv.DEMO and is_demo_account(user.email):
        raise AppError(403, "DEMO_ACCOUNT_LOCKED", "Demo accounts cannot be changed.")


def ensure_another_super_admin(db: Session, user: User) -> None:
    """Refuse to demote or deactivate the last active super_admin.

    The super_admin rows are locked so two simultaneous requests cannot each
    demote one of the last two admins.
    """
    admins = db.scalars(
        select(User.id).where(User.role == "super_admin", User.is_active).with_for_update()
    ).all()
    if not any(admin_id != user.id for admin_id in admins):
        raise AppError(400, "LAST_SUPER_ADMIN", "At least one active super_admin must remain.")


@router.get("", response_model=Page[UserOut])
def list_users(
    db: DbSession,
    _admin: SuperAdmin,
    q: SearchText = None,
    role: Role | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[UserOut]:
    """List login accounts. q searches the login email."""
    query = select(User)
    if q:
        query = query.where(User.email.ilike(like_pattern(q), escape="\\"))
    if role:
        query = query.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = db.scalars(
        query.options(selectinload(User.employee)).order_by(User.id).limit(limit).offset(offset)
    ).all()
    return Page[UserOut](items=[UserOut.model_validate(u) for u in users], total=total)


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DbSession, admin: SuperAdmin) -> UserOut:
    """Create a login, optionally linked to an employee record."""
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise AppError(400, "EMAIL_ALREADY_EXISTS", "A login with this email already exists.")
    employee = (
        get_linkable_employee(db, body.employee_id, None) if body.employee_id is not None else None
    )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        employee=employee,
        language=body.language,
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        admin,
        "USER_CREATED",
        "user",
        user.id,
        {"email": user.email, "role": user.role, "employee_id": body.employee_id},
    )
    commit_or_conflict(db)
    return UserOut.model_validate(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, db: DbSession, admin: SuperAdmin, settings: AppSettings
) -> UserOut:
    """Change role, activate or deactivate, relink, or reset the password.

    An admin cannot change their own role or deactivate their own account,
    and the last active super_admin cannot be demoted or deactivated.
    """
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "The user does not exist.")
    check_not_demo_account(user, settings)
    changes = body.changes()

    if user.id == admin.id:
        if "role" in changes and changes["role"] != user.role:
            raise AppError(400, "CANNOT_CHANGE_OWN_ROLE", "You cannot change your own role.")
        if changes.get("is_active") is False:
            raise AppError(400, "CANNOT_DEACTIVATE_SELF", "You cannot deactivate your own account.")
    losing_admin = user.role == "super_admin" and user.is_active
    if losing_admin and (
        changes.get("role", "super_admin") != "super_admin" or changes.get("is_active") is False
    ):
        ensure_another_super_admin(db, user)

    audit_detail: dict[str, object] = {}
    for field in ("role", "is_active", "language"):
        if field in changes and changes[field] != getattr(user, field):
            audit_detail[field] = {"old": getattr(user, field), "new": changes[field]}
            setattr(user, field, changes[field])
    if "employee_id" in changes and changes["employee_id"] != user.employee_id:
        old_id, new_id = user.employee_id, body.employee_id
        user.employee = get_linkable_employee(db, new_id, user.id) if new_id is not None else None
        audit_detail["employee_id"] = {"old": old_id, "new": new_id}
    if "password" in changes:
        user.password_hash = hash_password(str(body.password))
        # Only the fact of a reset is logged, never the value.
        audit_detail["password_reset"] = True

    if audit_detail:
        audit_service.record(db, admin, "USER_UPDATED", "user", user.id, audit_detail)
        commit_or_conflict(db)
        db.refresh(user)
    return UserOut.model_validate(user)
