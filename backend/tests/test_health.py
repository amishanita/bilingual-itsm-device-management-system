"""Health endpoint, CORS policy, and the test-database guard."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import validate_test_database_url


def test_health_reports_ok_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_without_internal_details_when_database_is_down(
    client: TestClient,
) -> None:
    from app.core.database import get_db
    from app.main import app

    # Port 1 has no PostgreSQL server, so the connection always fails.
    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/missing_test",
        connect_args={"connect_timeout": 2},
    )
    dead_sessions = sessionmaker(bind=dead_engine)

    def broken_get_db() -> Iterator[Session]:
        session = dead_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = broken_get_db
    response = client.get("/api/health")
    dead_engine.dispose()

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "DATABASE_UNAVAILABLE", "message": "The database is not available."}
    }
    body = response.text.lower()
    for leaked in ("psycopg", "traceback", "127.0.0.1", "nobody", "operationalerror"):
        assert leaked not in body


def test_cors_allows_only_the_configured_frontend_origin(client: TestClient) -> None:
    from app.core.config import get_settings

    allowed = get_settings().frontend_origin
    ok = client.get("/api/health", headers={"Origin": allowed})
    assert ok.headers.get("access-control-allow-origin") == allowed

    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


@pytest.mark.parametrize(
    ("test_url", "app_url"),
    [
        (None, "postgresql+psycopg://u:p@db:5432/itsm"),
        ("", "postgresql+psycopg://u:p@db:5432/itsm"),
        ("postgresql+psycopg://u:p@db:5432/itsm", "postgresql+psycopg://u:p@db:5432/other"),
        (
            "postgresql+psycopg://u:p@db:5432/itsm_test",
            "postgresql+psycopg://x:y@db:5432/itsm_test",
        ),
    ],
)
def test_guard_rejects_unsafe_test_database_urls(test_url: str | None, app_url: str) -> None:
    with pytest.raises(ValueError):
        validate_test_database_url(test_url, app_url)


def test_guard_accepts_a_separate_test_database() -> None:
    url = "postgresql+psycopg://u:p@db:5432/itsm_test"
    assert validate_test_database_url(url, "postgresql+psycopg://u:p@db:5432/itsm") == url


def test_api_docs_are_served_under_api(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"]
    assert client.get("/docs").status_code == 404


def test_api_docs_are_off_in_production() -> None:
    from app.core.config import AppEnv
    from app.main import docs_paths

    assert docs_paths(AppEnv.PRODUCTION) == {
        "docs_url": None,
        "openapi_url": None,
        "redoc_url": None,
    }
    assert docs_paths(AppEnv.DEMO)["docs_url"] == "/api/docs"
