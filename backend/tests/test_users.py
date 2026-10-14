"""Phase 4 tests: login account management (super_admin only)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import AppEnv, get_settings
from app.core.errors import AppError
from app.core.security import verify_password
from app.models import AuditLog, User
from app.routers.users import ensure_another_super_admin
from app.services import audit_service
from tests.helpers import (
    PASSWORD,
    employee_by_code,
    error_code,
    headers_as,
    make_settings,
    user_by_email,
)

ADMIN = "admin@demo"
NEW_USER = {"email": "tanaka@demo", "password": "first-pass-123", "role": "employee"}


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


# Who may use the endpoints


@pytest.mark.parametrize("email", ["it@demo", "manager@demo", "employee@demo"])
def test_only_super_admin_can_list_or_create_users(
    client: TestClient, db: Session, email: str
) -> None:
    headers = headers_as(db, email)
    assert client.get("/api/users", headers=headers).status_code == 403
    response = client.post("/api/users", json=NEW_USER, headers=headers)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert db.scalar(select(func.count()).select_from(User)) == 4


@pytest.mark.parametrize("email", ["it@demo", "manager@demo", "employee@demo"])
def test_only_super_admin_can_change_roles(client: TestClient, db: Session, email: str) -> None:
    """No other role can promote anyone, including themselves."""
    me = user_by_email(db, email)
    response = client.put(
        f"/api/users/{me.id}", json={"role": "super_admin"}, headers=headers_as(db, email)
    )
    assert response.status_code == 403
    assert user_by_email(db, email).role == me.role


def test_users_endpoints_require_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/users").status_code == 401
    assert client.put("/api/users/1", json={"role": "employee"}).status_code == 401


# Listing


def test_list_users_hides_password_hashes(client: TestClient, db: Session) -> None:
    response = client.get("/api/users", headers=headers_as(db, ADMIN))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert {u["email"] for u in body["items"]} == {
        "admin@demo",
        "it@demo",
        "manager@demo",
        "employee@demo",
    }
    assert "password_hash" not in response.text and "$2b$" not in response.text


def test_list_users_filters_and_paginates(client: TestClient, db: Session) -> None:
    headers = headers_as(db, ADMIN)
    managers = client.get("/api/users?role=manager", headers=headers).json()
    assert [u["email"] for u in managers["items"]] == ["manager@demo"]
    page = client.get("/api/users?limit=2&offset=2", headers=headers).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert client.get("/api/users?q=it@", headers=headers).json()["total"] == 1
    # A literal % must not act as a wildcard.
    assert client.get("/api/users?q=%25", headers=headers).json()["total"] == 0
    assert client.get("/api/users?limit=500", headers=headers).status_code == 422


# Creating


def test_create_user_and_log_in(client: TestClient, db: Session) -> None:
    free_employee = employee_by_code(db, "E0003")
    body = {**NEW_USER, "employee_id": free_employee.id, "language": "en"}
    response = client.post("/api/users", json=body, headers=headers_as(db, ADMIN))
    assert response.status_code == 201
    created = response.json()
    assert created["role"] == "employee"
    assert created["language"] == "en"
    assert created["employee"]["employee_code"] == "E0003"

    login = client.post(
        "/api/auth/login", json={"email": "tanaka@demo", "password": "first-pass-123"}
    )
    assert login.status_code == 200

    entry = audit_rows(db, "USER_CREATED")[0]
    assert entry.detail == {
        "email": "tanaka@demo",
        "role": "employee",
        "employee_id": free_employee.id,
    }
    assert entry.user_id == user_by_email(db, ADMIN).id


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"email": "it@demo"}, "EMAIL_ALREADY_EXISTS"),
        ({"email": " IT@Demo "}, "EMAIL_ALREADY_EXISTS"),
        ({"employee_id": 99999}, "EMPLOYEE_NOT_FOUND"),
    ],
)
def test_create_user_business_rules(
    client: TestClient, db: Session, change: dict, code: str
) -> None:
    response = client.post("/api/users", json={**NEW_USER, **change}, headers=headers_as(db, ADMIN))
    assert response.status_code == 400
    assert error_code(response) == code
    assert audit_rows(db, "USER_CREATED") == []


def test_cannot_link_an_employee_that_already_has_a_login(client: TestClient, db: Session) -> None:
    taken = employee_by_code(db, "E0010")  # linked to employee@demo
    response = client.post(
        "/api/users", json={**NEW_USER, "employee_id": taken.id}, headers=headers_as(db, ADMIN)
    )
    assert error_code(response) == "EMPLOYEE_ALREADY_LINKED"


def test_cannot_link_a_leaver(client: TestClient, db: Session) -> None:
    leaver = employee_by_code(db, "E0029")
    response = client.post(
        "/api/users", json={**NEW_USER, "employee_id": leaver.id}, headers=headers_as(db, ADMIN)
    )
    assert error_code(response) == "EMPLOYEE_HAS_LEFT"


@pytest.mark.parametrize(
    "change",
    [
        {"role": "root"},
        {"password": "short"},
        {"password": "x" * 73},
        {"email": ""},
        {"is_active": False},  # not a create field
    ],
)
def test_create_user_validation(client: TestClient, db: Session, change: dict) -> None:
    response = client.post("/api/users", json={**NEW_USER, **change}, headers=headers_as(db, ADMIN))
    assert response.status_code == 422


# Updating


def test_change_role_and_audit(client: TestClient, db: Session) -> None:
    target = user_by_email(db, "employee@demo")
    response = client.put(
        f"/api/users/{target.id}", json={"role": "manager"}, headers=headers_as(db, ADMIN)
    )
    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    assert audit_rows(db, "USER_UPDATED")[0].detail == {
        "role": {"old": "employee", "new": "manager"}
    }


def test_user_cannot_deactivate_their_own_account(client: TestClient, db: Session) -> None:
    admin = user_by_email(db, ADMIN)
    response = client.put(
        f"/api/users/{admin.id}", json={"is_active": False}, headers=headers_as(db, ADMIN)
    )
    assert response.status_code == 400
    assert error_code(response) == "CANNOT_DEACTIVATE_SELF"
    assert user_by_email(db, ADMIN).is_active


def test_user_cannot_change_their_own_role(client: TestClient, db: Session) -> None:
    admin = user_by_email(db, ADMIN)
    response = client.put(
        f"/api/users/{admin.id}", json={"role": "employee"}, headers=headers_as(db, ADMIN)
    )
    assert error_code(response) == "CANNOT_CHANGE_OWN_ROLE"


def test_a_super_admin_can_demote_another_super_admin(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == "it@demo").values(role="super_admin"))
    db.commit()
    admin = user_by_email(db, ADMIN)
    response = client.put(
        f"/api/users/{admin.id}", json={"role": "it_admin"}, headers=headers_as(db, "it@demo")
    )
    assert response.status_code == 200


def test_last_super_admin_guard(db: Session) -> None:
    """Through the API the acting admin always remains, so this guard matters when two
    admins demote each other at the same moment. The row lock serializes them, and the
    second request then finds no other admin. Checked directly here."""
    admin = user_by_email(db, ADMIN)
    with pytest.raises(AppError) as error:
        ensure_another_super_admin(db, admin)
    assert error.value.code == "LAST_SUPER_ADMIN"
    db.rollback()

    db.execute(update(User).where(User.email == "it@demo").values(role="super_admin"))
    db.commit()
    ensure_another_super_admin(db, user_by_email(db, ADMIN))
    db.rollback()


def test_deactivated_user_is_locked_out_immediately(client: TestClient, db: Session) -> None:
    target = user_by_email(db, "employee@demo")
    their_headers = headers_as(db, "employee@demo")
    client.put(f"/api/users/{target.id}", json={"is_active": False}, headers=headers_as(db, ADMIN))
    assert error_code(client.get("/api/auth/me", headers=their_headers)) == "ACCOUNT_DISABLED"
    login = client.post("/api/auth/login", json={"email": "employee@demo", "password": PASSWORD})
    assert error_code(login) == "ACCOUNT_DISABLED"


def test_password_reset_is_not_logged(client: TestClient, db: Session) -> None:
    target = user_by_email(db, "employee@demo")
    response = client.put(
        f"/api/users/{target.id}",
        json={"password": "reset-pass-456"},
        headers=headers_as(db, ADMIN),
    )
    assert response.status_code == 200
    assert verify_password("reset-pass-456", user_by_email(db, "employee@demo").password_hash)
    entry = audit_rows(db, "USER_UPDATED")[0]
    assert entry.detail == {"password_reset": True}
    assert "reset-pass-456" not in str(entry.detail)


def test_link_and_unlink_employee(client: TestClient, db: Session) -> None:
    target = user_by_email(db, "it@demo")
    other = employee_by_code(db, "E0004")
    headers = headers_as(db, ADMIN)
    linked = client.put(f"/api/users/{target.id}", json={"employee_id": other.id}, headers=headers)
    assert linked.json()["employee"]["employee_code"] == "E0004"
    unlinked = client.put(f"/api/users/{target.id}", json={"employee_id": None}, headers=headers)
    assert unlinked.json()["employee"] is None


@pytest.mark.parametrize(
    "body",
    [{"role": None}, {"is_active": None}, {"role": "owner"}, {"email": "new@demo"}],
)
def test_update_user_validation(client: TestClient, db: Session, body: dict) -> None:
    target = user_by_email(db, "employee@demo")
    response = client.put(f"/api/users/{target.id}", json=body, headers=headers_as(db, ADMIN))
    assert response.status_code == 422


def test_update_unknown_user_is_404(client: TestClient, db: Session) -> None:
    response = client.put(
        "/api/users/99999", json={"role": "employee"}, headers=headers_as(db, ADMIN)
    )
    assert response.status_code == 404
    assert error_code(response) == "USER_NOT_FOUND"


def test_no_change_writes_no_audit_row(client: TestClient, db: Session) -> None:
    target = user_by_email(db, "employee@demo")
    client.put(f"/api/users/{target.id}", json={"role": "employee"}, headers=headers_as(db, ADMIN))
    assert audit_rows(db, "USER_UPDATED") == []


def test_demo_accounts_are_locked_in_demo_mode(client: TestClient, db: Session) -> None:
    from app.main import app

    target = user_by_email(db, "employee@demo")
    headers = headers_as(db, ADMIN)
    app.dependency_overrides[get_settings] = lambda: make_settings(AppEnv.DEMO)
    response = client.put(f"/api/users/{target.id}", json={"is_active": False}, headers=headers)
    assert response.status_code == 403
    assert error_code(response) == "DEMO_ACCOUNT_LOCKED"
    assert user_by_email(db, "employee@demo").is_active


def test_failed_audit_rolls_back_the_change(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The change and its audit row are one transaction: no audit, no change."""
    target = user_by_email(db, "employee@demo")

    def broken_record(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(audit_service, "record", broken_record)
    response = client.put(
        f"/api/users/{target.id}", json={"role": "manager"}, headers=headers_as(db, ADMIN)
    )
    assert response.status_code == 500
    assert user_by_email(db, "employee@demo").role == "employee"
