"""Authentication endpoints: login, profile, language preference, password change."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.core.config import AppEnv
from app.core.demo import is_demo_account
from app.core.deps import AppSettings, CurrentUser, DbSession
from app.core.errors import AppError
from app.core.limiter import LOGIN_LIMIT, limiter
from app.core.security import (
    ACCESS_TOKEN_MINUTES,
    burn_password_check,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import (
    LanguageUpdate,
    LoginRequest,
    PasswordChange,
    TokenResponse,
    UserProfile,
)
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


def invalid_credentials() -> AppError:
    """One error for unknown email and wrong password alike."""
    return AppError(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
def login(
    request: Request,  # noqa: ARG001 - slowapi reads the client address from it
    body: LoginRequest,
    db: DbSession,
    settings: AppSettings,
) -> TokenResponse:
    """Exchange email and password for a 60-minute access token.

    Unknown email and wrong password give the same 401 and take the same time,
    so the endpoint does not reveal which accounts exist. Limited to 5 requests
    per minute per client IP.
    """
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        burn_password_check(body.password)
        raise invalid_credentials()
    if not verify_password(body.password, user.password_hash):
        raise invalid_credentials()
    # Checked after the password, so this answer only goes to someone who knows it.
    if not user.is_active:
        raise AppError(401, "ACCOUNT_DISABLED", "This account has been deactivated.")

    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=ACCESS_TOKEN_MINUTES * 60,
        user=UserProfile.model_validate(user),
    )


@router.get("/me", response_model=UserProfile)
def read_me(user: CurrentUser) -> UserProfile:
    """Return the logged-in user's profile."""
    return UserProfile.model_validate(user)


@router.put("/me/language", response_model=UserProfile)
def update_language(body: LanguageUpdate, user: CurrentUser, db: DbSession) -> UserProfile:
    """Save the user's interface language (ja or en)."""
    if user.language != body.language:
        old_language = user.language
        user.language = body.language
        audit_service.record(
            db,
            user,
            "USER_LANGUAGE_CHANGED",
            "user",
            user.id,
            {"old": old_language, "new": body.language},
        )
        db.commit()
    return UserProfile.model_validate(user)


@router.post("/change-password", status_code=204)
def change_password(
    body: PasswordChange, user: CurrentUser, db: DbSession, settings: AppSettings
) -> Response:
    """Change the logged-in user's password after checking the current one.

    In demo mode the shared demo accounts cannot change their password (Part B.1),
    otherwise one visitor could lock everyone else out.
    """
    if settings.app_env == AppEnv.DEMO and is_demo_account(user.email):
        raise AppError(403, "DEMO_ACCOUNT_LOCKED", "Demo accounts cannot change their password.")
    if not verify_password(body.current_password, user.password_hash):
        raise AppError(400, "INVALID_CURRENT_PASSWORD", "The current password is incorrect.")
    if body.new_password == body.current_password:
        raise AppError(
            400, "PASSWORD_UNCHANGED", "The new password must differ from the current one."
        )

    user.password_hash = hash_password(body.new_password)
    # The detail stays empty on purpose: no password data goes into the audit log.
    audit_service.record(db, user, "USER_PASSWORD_CHANGED", "user", user.id)
    db.commit()
    return Response(status_code=204)
