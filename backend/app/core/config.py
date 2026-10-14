"""Application settings loaded from environment variables or a .env file."""

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    """Runtime modes. The seed script and demo-account rules depend on this value."""

    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


# The value shipped in .env.example. Starting with it would mean every copy of the
# project signs tokens with the same publicly known key.
JWT_SECRET_PLACEHOLDER = "replace-with-a-long-random-value"  # noqa: S105 - known-bad value to reject
JWT_SECRET_MIN_LENGTH = 32


class DatabaseSettings(BaseSettings):
    """The settings needed to reach the database, and nothing else.

    Migrations and the engine use only this, so `alembic upgrade` runs without
    application secrets such as JWT_SECRET (for example in CI).
    Values come from the process environment first, then from .env.
    Unknown variables are ignored.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str


class Settings(DatabaseSettings):
    """Full application settings for the API and the seed script."""

    app_env: AppEnv = AppEnv.DEVELOPMENT
    frontend_origin: str = "http://localhost:8080"
    # Signing key for HS256 access tokens. Required; the app refuses to start without it.
    jwt_secret: SecretStr
    # Only the seed script needs this. SecretStr keeps it out of logs and reprs.
    demo_password: SecretStr | None = None

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_must_be_strong(cls, value: SecretStr) -> SecretStr:
        """Reject a short JWT secret or the example placeholder."""
        secret = value.get_secret_value()
        if secret == JWT_SECRET_PLACEHOLDER:
            raise ValueError("JWT_SECRET still has the example value. Generate a random one.")
        if len(secret) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {JWT_SECRET_MIN_LENGTH} characters.")
        return value


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Return the cached database settings."""
    return DatabaseSettings()


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
