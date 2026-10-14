"""Shared pytest fixtures and the test-database safety guard.

The suite refuses to start unless TEST_DATABASE_URL is set, names a database
ending in _test, and points somewhere other than DATABASE_URL. Later phases
create and drop tables in that database, so this guard protects real data.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


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


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Engine bound to the validated test database."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def client(test_engine: Engine) -> Iterator[TestClient]:
    """TestClient whose database dependency uses the test database."""
    from app.core.database import get_db
    from app.main import app

    session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
