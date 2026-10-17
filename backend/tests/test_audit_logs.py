"""GET /api/audit-logs: super_admin only, newest first, with filters."""

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from tests.helpers import PASSWORD, error_code, headers_as

ADMIN = "admin@demo"
IT = "it@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"

ARTICLE = {
    "category": "software",
    "title_en": "Audit test",
    "body_en": "Body.",
    "title_ja": "監査テスト",
    "body_ja": "本文です。",
}


def logs(client: TestClient, db: Session, email: str = ADMIN, **params: object) -> Response:
    return client.get("/api/audit-logs", headers=headers_as(db, email), params=params)


def make_change(client: TestClient, db: Session) -> int:
    """Create a FAQ article as IT, which writes one FAQ_CREATED audit row."""
    response = client.post("/api/faq", json=ARTICLE, headers=headers_as(db, IT))
    assert response.status_code == 201
    return response.json()["id"]


def test_requires_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/audit-logs").status_code == 401


@pytest.mark.parametrize("email", [IT, MANAGER, EMPLOYEE])
def test_only_super_admin_can_read(client: TestClient, db: Session, email: str) -> None:
    response = logs(client, db, email)
    assert response.status_code == 403


def test_super_admin_sees_a_change_with_who_did_it(client: TestClient, db: Session) -> None:
    article_id = make_change(client, db)
    body = logs(client, db, action="FAQ_CREATED", entity_id=article_id).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["entity"] == "faq"
    assert row["user_email"] == IT
    assert row["user_id"] == db.scalar(select(User.id).where(User.email == IT))


def test_total_matches_the_table(client: TestClient, db: Session) -> None:
    make_change(client, db)
    expected = db.scalar(select(func.count()).select_from(AuditLog))
    assert logs(client, db).json()["total"] == expected


def test_newest_first(client: TestClient, db: Session) -> None:
    first = make_change(client, db)
    second = make_change(client, db)
    ids = [row["entity_id"] for row in logs(client, db, action="FAQ_CREATED").json()["items"]]
    assert ids.index(second) < ids.index(first)


def test_filters_by_entity_and_user(client: TestClient, db: Session) -> None:
    make_change(client, db)
    it_id = db.scalar(select(User.id).where(User.email == IT))
    for row in logs(client, db, entity="faq", user_id=it_id).json()["items"]:
        assert row["entity"] == "faq" and row["user_id"] == it_id


def test_action_filter_is_case_insensitive(client: TestClient, db: Session) -> None:
    make_change(client, db)
    assert logs(client, db, action="faq_created").json()["total"] >= 1


def test_limit_and_offset(client: TestClient, db: Session) -> None:
    for _ in range(3):
        make_change(client, db)
    page = logs(client, db, action="FAQ_CREATED", limit=2).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    rest = logs(client, db, action="FAQ_CREATED", limit=2, offset=2).json()
    assert len(rest["items"]) == 1


def test_time_range(client: TestClient, db: Session) -> None:
    make_change(client, db)
    newest = db.scalar(select(func.max(AuditLog.created_at)))
    assert logs(client, db, since=newest.isoformat()).json()["total"] >= 1
    assert logs(client, db, until=newest.isoformat(), action="FAQ_CREATED").json()["total"] == 0


def test_reversed_time_range_is_rejected(client: TestClient, db: Session) -> None:
    response = logs(client, db, since="2026-02-01T00:00:00Z", until="2026-01-01T00:00:00Z")
    assert response.status_code == 400
    assert error_code(response) == "INVALID_TIME_RANGE"


@pytest.mark.parametrize("params", [{"action": "DROP TABLE"}, {"entity": "x" * 65}, {"limit": 0}])
def test_bad_filters_are_422(client: TestClient, db: Session, params: dict[str, object]) -> None:
    assert logs(client, db, **params).status_code == 422


def test_password_change_is_listed_without_password_data(client: TestClient, db: Session) -> None:
    new_password = "a-brand-new-pass-123"
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": new_password},
        headers=headers_as(db, EMPLOYEE),
    )
    assert response.status_code == 204
    body = logs(client, db, action="USER_PASSWORD_CHANGED").json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["user_email"] == EMPLOYEE and row["detail"] == {}
    text = str(logs(client, db, limit=200).json())
    assert PASSWORD not in text and new_password not in text and "$2b$" not in text
