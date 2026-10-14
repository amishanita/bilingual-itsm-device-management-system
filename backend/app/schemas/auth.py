"""Schemas for login, profile, language, and password change."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.core.security import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH


def max_72_bytes(value: str) -> str:
    """Reject passwords bcrypt would truncate. Longer input is a 422, never cut short."""
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"must be at most {MAX_PASSWORD_BYTES} bytes in UTF-8")
    return value


# Emails are compared lowercase. Demo logins like admin@demo have no domain
# suffix, so this is a plain string with a length limit, not EmailStr.
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=254)
]
# For checking an existing password: only the upper bound applies.
SubmittedPassword = Annotated[str, Field(min_length=1), AfterValidator(max_72_bytes)]
# For setting a new password: the full 8 characters to 72 bytes policy.
NewPassword = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH), AfterValidator(max_72_bytes)]
Language = Literal["ja", "en"]


class StrictModel(BaseModel):
    """Input model that rejects unknown fields, so a client cannot slip in extra
    attributes such as a role."""

    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    """Credentials for POST /api/auth/login."""

    email: Email
    password: SubmittedPassword


class LanguageUpdate(StrictModel):
    """Body for PUT /api/auth/me/language."""

    language: Language


class PasswordChange(StrictModel):
    """Body for POST /api/auth/change-password."""

    current_password: SubmittedPassword
    new_password: NewPassword


class EmployeeSummary(BaseModel):
    """The employee record linked to a login."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    name: str
    department: str


class UserProfile(BaseModel):
    """The logged-in user as returned by /api/auth/me. Never includes the hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    language: Language
    is_active: bool
    employee: EmployeeSummary | None


class TokenResponse(BaseModel):
    """Successful login result."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type name
    expires_in: int
    user: UserProfile
