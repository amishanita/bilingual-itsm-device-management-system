"""Shared pytest fixtures and the test-database safety guard.

The suite refuses to start unless TEST_DATABASE_URL is set, names a database
ending in _test, and points somewhere other than DATABASE_URL. Later phases
create and drop tables in that database, so this guard protects real data.
"""

import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent

# A fresh signing key for every test run, so no secret is stored in the repository.
# Set before any app module is imported, because settings are read at import time.
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))


def validate_test_database_url(test_url: str | None, app_url: str | None) -> str:
    """Return the test database URL if it is safe to use, otherwise raise ValueError."""
    if not test_url:
        raise ValueError("TEST_DATABASE_URL is not set.")
    test = make_url(test_url)
    if not test.database or not test.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending with _test.")
    if app_url:
        app = make_url(app_url)
        same_target = (test.host, test.port, test.database) == (app.host, app.port, app.database)
        if same_target:
            raise ValueError("TEST_DATABASE_URL must differ from DATABASE_URL.")
    return test_url


def pytest_configure(config: pytest.Config) -> None:
    """Stop the whole run before any test touches a database that is not a test database."""
    try:
        validate_test_database_url(
            os.environ.get("TEST_DATABASE_URL"), os.environ.get("DATABASE_URL")
        )
    except ValueError as exc:
        raise pytest.UsageError(f"Unsafe test database configuration: {exc}") from exc


def alembic_config(database_url: str) -> Config:
    """Alembic config pointed at an explicit database instead of DATABASE_URL."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Engine bound to the validated test database, migrated from empty to head.

    Downgrading to base first means every run starts from an empty schema,
    which also exercises the full downgrade path.
    """
    url = os.environ["TEST_DATABASE_URL"]
    config = alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is always rolled back.

    Commits inside the test become savepoints, so nothing a test writes survives it.
    """
    with test_engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def client(test_engine: Engine) -> Iterator[TestClient]:
    """TestClient whose database dependency uses the test database."""
    from app.core.database import get_db
    from app.core.limiter import limiter
    from app.main import app

    session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # Rate limits are kept in memory; start every test with a clean count.
    limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
