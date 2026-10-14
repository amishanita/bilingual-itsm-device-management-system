"""Application settings loaded from environment variables or a .env file."""

from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    """Runtime modes. The seed script and demo-account rules depend on this value."""

    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed application settings.

    Values come from the process environment first, then from .env.
    Unknown variables are ignored so later phases can add keys to .env
    before the matching settings exist.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: AppEnv = AppEnv.DEVELOPMENT
    database_url: str
    frontend_origin: str = "http://localhost:8080"
    # Only the seed script needs this. SecretStr keeps it out of logs and reprs.
    demo_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
