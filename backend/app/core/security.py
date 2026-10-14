"""Password hashing with bcrypt.

bcrypt only uses the first 72 bytes of its input. Instead of silently ignoring
the rest, passwords outside 8 to 72 UTF-8 bytes are rejected (Part B.7).
"""

import bcrypt

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
