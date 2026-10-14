"""Phase 4 tests: employee CRUD, manager department isolation, and the leaver step.

Seed facts used here: manager@demo and employee@demo are in 営業部 (E0007-E0012).
E0001-E0006 are 情報システム部. E0029 has already left.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import AppEnv, get_settings
from app.models import AuditLog, Employee, User
from tests.helpers import (
    PASSWORD,
    employee_by_code,
    error_code,
    headers_as,
    make_settings,
    user_by_email,
)

IT = "it@demo"
MANAGER = "manager@demo"
SALES = "営業部"

NEW_EMPLOYEE = {
    "employee_code": "E0031",
    "name": "新井 一郎",
    "email": "ichiro.arai@example.co.jp",
    "department": "総務部",
    "position": "一般",
    "join_date": "2026-10-01",
}


def employee_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Employee)) or 0


# Access by role


def test_employee_role_cannot_use_employee_endpoints(client: TestClient, db: Session) -> None:
    """employee@demo calling it_admin and manager endpoints gets 403."""
    headers = headers_as(db, "employee@demo")
    sales_colleague = employee_by_code(db, "E0011")
    assert client.get("/api/employees", headers=headers).status_code == 403
    assert client.get(f"/api/employees/{sales_colleague.id}", headers=headers).status_code == 403
    response = client.post("/api/employees", json=NEW_EMPLOYEE, headers=headers)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert employee_count(db) == 30


@pytest.mark.parametrize("email", ["manager@demo", "employee@demo"])
def test_only_it_staff_can_write(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    target = employee_by_code(db, "E0011")
    assert client.post("/api/employees", json=NEW_EMPLOYEE, headers=headers).status_code == 403
    assert (
        client.put(
            f"/api/employees/{target.id}", json={"position": "部長"}, headers=headers
        ).status_code
        == 403
    )
    assert client.delete(f"/api/employees/{target.id}", headers=headers).status_code == 403
    assert employee_by_code(db, "E0011").status == "active"


def test_endpoints_require_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/employees").status_code == 401


# Manager isolation


def test_manager_list_contains_only_their_department(client: TestClient, db: Session) -> None:
    response = client.get("/api/employees?limit=200", headers=headers_as(db, MANAGER))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 6
    assert {e["department"] for e in body["items"]} == {SALES}


def test_manager_cannot_widen_scope_with_a_filter(client: TestClient, db: Session) -> None:
    """Asking for another department returns nothing rather than that department."""
    response = client.get(
        "/api/employees?department=情報システム部", headers=headers_as(db, MANAGER)
    )
    assert response.json() == {"items": [], "total": 0}


def test_manager_gets_404_for_other_departments(client: TestClient, db: Session) -> None:
    other = employee_by_code(db, "E0001")
    response = client.get(f"/api/employees/{other.id}", headers=headers_as(db, MANAGER))
    assert response.status_code == 404
    assert error_code(response) == "EMPLOYEE_NOT_FOUND"
    # Same answer as an id that does not exist at all.
    missing = client.get("/api/employees/99999", headers=headers_as(db, MANAGER))
    assert missing.json() == response.json()


def test_manager_can_read_own_department_record(client: TestClient, db: Session) -> None:
    own = employee_by_code(db, "E0012")
    response = client.get(f"/api/employees/{own.id}", headers=headers_as(db, MANAGER))
    assert response.status_code == 200
    assert response.json()["employee_code"] == "E0012"


def test_manager_without_linked_employee_sees_nothing(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == MANAGER).values(employee_id=None))
    db.commit()
    response = client.get("/api/employees", headers=headers_as(db, MANAGER))
    assert response.json() == {"items": [], "total": 0}


def test_manager_scope_follows_their_employee_record(client: TestClient, db: Session) -> None:
    """The department comes from the database, so moving the manager moves the scope."""
    manager_employee = employee_by_code(db, "E0007")
    db.execute(
        update(Employee).where(Employee.id == manager_employee.id).values(department="経理部")
    )
    db.commit()
    body = client.get("/api/employees", headers=headers_as(db, MANAGER)).json()
    assert {e["department"] for e in body["items"]} == {"経理部"}


# Listing for IT staff


def test_it_admin_sees_everyone_and_can_filter(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    assert client.get("/api/employees", headers=headers).json()["total"] == 30
    assert client.get("/api/employees?status=left", headers=headers).json()["total"] == 1
    by_dept = client.get(f"/api/employees?department={SALES}", headers=headers).json()
    assert by_dept["total"] == 6
    by_name = client.get("/api/employees?q=佐藤", headers=headers).json()
    assert [e["employee_code"] for e in by_name["items"]] == ["E0001"]
    by_code = client.get("/api/employees?q=e0030", headers=headers).json()
    assert by_code["total"] == 1


def test_super_admin_has_it_admin_access(client: TestClient, db: Session) -> None:
    response = client.post(
        "/api/employees", json=NEW_EMPLOYEE, headers=headers_as(db, "admin@demo")
    )
    assert response.status_code == 201


# Create and update


def test_create_employee_and_audit(client: TestClient, db: Session) -> None:
    response = client.post("/api/employees", json=NEW_EMPLOYEE, headers=headers_as(db, IT))
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "active"
    assert created["name"] == "新井 一郎"
    assert employee_count(db) == 31
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_CREATED")).one()
    assert (entry.entity, entry.entity_id) == ("employee", created["id"])


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"employee_code": "E0001"}, "EMPLOYEE_CODE_EXISTS"),
        ({"email": "kenta.sato@example.co.jp"}, "EMAIL_ALREADY_EXISTS"),
    ],
)
def test_create_rejects_duplicates(
    client: TestClient, db: Session, change: dict, code: str
) -> None:
    response = client.post(
        "/api/employees", json={**NEW_EMPLOYEE, **change}, headers=headers_as(db, IT)
    )
    assert response.status_code == 400
    assert error_code(response) == code
    assert employee_count(db) == 30


@pytest.mark.parametrize(
    "change",
    [
        {"status": "left"},  # leavers go through DELETE
        {"status": "retired"},
        {"name": ""},
        {"name": "x" * 101},
        {"join_date": "not-a-date"},
        {"employee_code": "x" * 21},
        {"id": 5},
    ],
)
def test_create_validation(client: TestClient, db: Session, change: dict) -> None:
    response = client.post(
        "/api/employees", json={**NEW_EMPLOYEE, **change}, headers=headers_as(db, IT)
    )
    assert response.status_code == 422


def test_update_changes_only_sent_fields_and_audits(client: TestClient, db: Session) -> None:
    target = employee_by_code(db, "E0011")
    response = client.put(
        f"/api/employees/{target.id}",
        json={"position": "主任", "department": "総務部"},
        headers=headers_as(db, IT),
    )
    assert response.status_code == 200
    updated = employee_by_code(db, "E0011")
    assert (updated.position, updated.department, updated.name) == ("主任", "総務部", "吉田 健一")
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_UPDATED")).one()
    assert entry.detail == {
        "position": {"old": "一般", "new": "主任"},
        "department": {"old": SALES, "new": "総務部"},
    }


def test_update_rejects_another_employees_email(client: TestClient, db: Session) -> None:
    target = employee_by_code(db, "E0011")
    response = client.put(
        f"/api/employees/{target.id}",
        json={"email": "kenta.sato@example.co.jp"},
        headers=headers_as(db, IT),
    )
    assert error_code(response) == "EMAIL_ALREADY_EXISTS"


def test_update_keeping_own_email_is_fine(client: TestClient, db: Session) -> None:
    target = employee_by_code(db, "E0011")
    response = client.put(
        f"/api/employees/{target.id}", json={"email": target.email}, headers=headers_as(db, IT)
    )
    assert response.status_code == 200


@pytest.mark.parametrize("body", [{"status": "left"}, {"name": None}, {"department": ""}])
def test_update_validation(client: TestClient, db: Session, body: dict) -> None:
    target = employee_by_code(db, "E0011")
    response = client.put(f"/api/employees/{target.id}", json=body, headers=headers_as(db, IT))
    assert response.status_code == 422


def test_rehire_sets_a_leaver_active_again(client: TestClient, db: Session) -> None:
    leaver = employee_by_code(db, "E0029")
    response = client.put(
        f"/api/employees/{leaver.id}", json={"status": "active"}, headers=headers_as(db, IT)
    )
    assert response.json()["status"] == "active"


# Leaver step (DELETE)


def test_delete_marks_left_and_keeps_the_record(client: TestClient, db: Session) -> None:
    target = employee_by_code(db, "E0011")
    response = client.delete(f"/api/employees/{target.id}", headers=headers_as(db, IT))
    assert response.status_code == 200
    assert response.json()["status"] == "left"
    assert employee_count(db) == 30
    assert employee_by_code(db, "E0011").status == "left"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_LEFT")).one()
    assert entry.detail == {"old_status": "active", "login_deactivated": None}


def test_delete_deactivates_the_leavers_login(client: TestClient, db: Session) -> None:
    target = employee_by_code(db, "E0010")  # employee@demo
    client.delete(f"/api/employees/{target.id}", headers=headers_as(db, IT))
    login_user = user_by_email(db, "employee@demo")
    assert login_user.is_active is False
    response = client.post("/api/auth/login", json={"email": "employee@demo", "password": PASSWORD})
    assert error_code(response) == "ACCOUNT_DISABLED"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_LEFT")).one()
    assert entry.detail["login_deactivated"] == login_user.id


def test_delete_twice_is_rejected(client: TestClient, db: Session) -> None:
    leaver = employee_by_code(db, "E0029")
    response = client.delete(f"/api/employees/{leaver.id}", headers=headers_as(db, IT))
    assert response.status_code == 400
    assert error_code(response) == "EMPLOYEE_ALREADY_LEFT"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "EMPLOYEE_LEFT")).all() == []


def test_delete_unknown_employee_is_404(client: TestClient, db: Session) -> None:
    assert client.delete("/api/employees/99999", headers=headers_as(db, IT)).status_code == 404


def test_demo_login_owner_cannot_be_marked_left_in_demo_mode(
    client: TestClient, db: Session
) -> None:
    from app.main import app

    target = employee_by_code(db, "E0010")
    headers = headers_as(db, IT)
    app.dependency_overrides[get_settings] = lambda: make_settings(AppEnv.DEMO)
    response = client.delete(f"/api/employees/{target.id}", headers=headers)
    assert response.status_code == 403
    assert employee_by_code(db, "E0010").status == "active"
    # Employees without a demo login can still leave in demo mode.
    plain = employee_by_code(db, "E0011")
    assert client.delete(f"/api/employees/{plain.id}", headers=headers).status_code == 200
