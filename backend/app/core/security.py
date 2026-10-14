"""Password hashing (bcrypt) and access tokens (JWT, HS256).

bcrypt only uses the first 72 bytes of its input. Instead of silently ignoring
the rest, passwords outside 8 to 72 UTF-8 bytes are rejected (Part B.7).
"""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from secrets import token_urlsafe

import bcrypt
import jwt

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60
TOKEN_TYPE = "access"  # noqa: S105 - a claim label, not a secret
REQUIRED_CLAIMS = ["sub", "exp", "iat", "type"]

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


class PasswordPolicyError(ValueError):
    """Raised when a password is too short or too long to hash safely."""


def validate_password(password: str) -> None:
    """Raise PasswordPolicyError unless the password is 8 characters to 72 UTF-8 bytes."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes in UTF-8.")


def hash_password(password: str) -> str:
    """Validate and hash a password. The returned string is safe to store."""
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if the password matches the stored hash.

    Over-long input returns False instead of being truncated to 72 bytes.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(encoded, password_hash.encode("ascii"))


@lru_cache
def _dummy_hash() -> str:
    """A throwaway hash, computed once, used when the login email does not exist."""
    return bcrypt.hashpw(token_urlsafe(16).encode("ascii"), bcrypt.gensalt()).decode("ascii")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check for an unknown email.

    Without this, a fast reply for unknown emails would reveal which accounts exist.
    """
    verify_password(password, _dummy_hash())


class TokenError(Exception):
    """Raised when an access token is missing claims, tampered with, or expired."""

    def __init__(self, expired: bool = False) -> None:
        super().__init__("expired" if expired else "invalid")
        self.expired = expired


def create_access_token(user_id: int, settings: Settings, now: datetime | None = None) -> str:
    """Issue a signed token for a user, valid for 60 minutes.

    The token carries only the user id. Role and active status are read from
    the database on every request, so a role change or deactivation takes
    effect immediately instead of when the token expires.
    """
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "type": TOKEN_TYPE,
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> int:
    """Verify a token and return the user id.

    The algorithm is pinned to HS256, so tokens signed with "none" or any other
    algorithm are rejected.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError(expired=True) from exc
    except jwt.PyJWTError as exc:
        raise TokenError() from exc

    if claims.get("type") != TOKEN_TYPE:
        raise TokenError()
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise TokenError()
    return int(subject)
