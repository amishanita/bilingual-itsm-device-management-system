"""Shared FastAPI dependencies: current user and role checks."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import TokenError, decode_access_token
from app.models import User

# auto_error=False so a missing header produces our own 401 body, not FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False)

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def unauthorized(code: str, message: str) -> AppError:
    """Build a 401 error with the Bearer challenge header."""
    return AppError(401, code, message, headers=BEARER_CHALLENGE)


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Return the logged-in user, or raise 401.

    The user is loaded from the database on every request. A deactivated or
    deleted account is rejected even while its token has not expired yet.
    """
    if credentials is None:
        raise unauthorized("NOT_AUTHENTICATED", "Authentication is required.")
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except TokenError as exc:
        if exc.expired:
            raise unauthorized("TOKEN_EXPIRED", "Your session has expired.") from exc
        raise unauthorized("INVALID_TOKEN", "The access token is not valid.") from exc

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("INVALID_TOKEN", "The access token is not valid.")
    if not user.is_active:
        raise unauthorized("ACCOUNT_DISABLED", "This account has been deactivated.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    """Build a dependency that allows only the given roles.

    Usage: user: Annotated[User, Depends(require_role("it_admin", "super_admin"))]
    Returns 401 when not logged in (from get_current_user) and 403 for other roles.
    """
    allowed = frozenset(roles)

    def check_role(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise AppError(403, "FORBIDDEN", "You do not have permission to do this.")
        return user

    return check_role


# Role groups. super_admin has full access, so it is included wherever it_admin is.
ADMIN_ROLES = ("it_admin", "super_admin")
STAFF_READ_ROLES = ("manager", "it_admin", "super_admin")

SuperAdmin = Annotated[User, Depends(require_role("super_admin"))]
ItAdmin = Annotated[User, Depends(require_role(*ADMIN_ROLES))]
ManagerOrAdmin = Annotated[User, Depends(require_role(*STAFF_READ_ROLES))]


def manager_department(user: User) -> str | None:
    """Return the department a manager may see (Part B.2).

    The department comes from the employee record linked to the manager's login,
    never from the request. A manager with no linked employee gets None and
    therefore sees no department-scoped data.
    """
    return user.employee.department if user.employee is not None else None
