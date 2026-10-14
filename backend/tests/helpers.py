"""Helpers shared by API tests: settings, login, and lookups."""

import os

from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings
from app.models import Employee, User

PASSWORD = "demo-pass-1234"


def make_settings(app_env: AppEnv = AppEnv.DEVELOPMENT) -> Settings:
    """Settings for the test database, independent of any .env file."""
    return Settings(
        _env_file=None,
        app_env=app_env,
        database_url=os.environ["TEST_DATABASE_URL"],
        jwt_secret=SecretStr(os.environ["JWT_SECRET"]),
        demo_password=SecretStr(PASSWORD),
    )


def login(client: TestClient, email: str = "employee@demo", password: str = PASSWORD) -> dict:
    """Log in and return the JSON body."""
    return client.post("/api/auth/login", json={"email": email, "password": password}).json()


def auth(token: str) -> dict[str, str]:
    """Authorization header for a token."""
    return {"Authorization": f"Bearer {token}"}


def token_for(client: TestClient, email: str = "employee@demo") -> str:
    """Log in as a demo account and return its access token."""
    return login(client, email)["access_token"]


def headers_for(client: TestClient, email: str) -> dict[str, str]:
    """Log in as a demo account and return ready-to-use headers."""
    return auth(token_for(client, email))


def user_by_email(db: Session, email: str) -> User:
    """Reload a user from the database, ignoring anything cached in the session."""
    db.expire_all()
    return db.scalars(select(User).where(User.email == email)).one()


def employee_by_code(db: Session, code: str) -> Employee:
    """Reload an employee from the database."""
    db.expire_all()
    return db.scalars(select(Employee).where(Employee.employee_code == code)).one()


def error_code(response: Response) -> str:
    """The code field of a standard error body."""
    return response.json()["detail"]["code"]


def headers_as(db: Session, email: str) -> dict[str, str]:
    """Headers with a token issued directly, skipping the login endpoint.

    Uses the same signing code as login, but does not count against the
    5-per-minute login limit, so a test can act as several roles.
    """
    from app.core.security import create_access_token

    return auth(create_access_token(user_by_email(db, email).id, make_settings()))
