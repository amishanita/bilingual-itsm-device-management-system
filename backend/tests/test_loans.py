"""Phase 7 tests: loans, overdue logic, loan returns, and the employee departure flow.

Seed facts used here. Open loans: PC-0019 (E0011, 営業部, overdue), SP-0041 (E0014,
overdue), TB-0053 (E0020, overdue), TB-0052 (E0026, due in 5 days). Returned loans:
PC-0021 and SP-0043 (device now returned), PC-0022 and SP-0044 (device now wiped).
manager@demo is in 営業部. E0016 is on leave.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, AuditLog, DeviceLoan, Employee, User
from app.services import audit_service, loan_service
from tests.helpers import employee_by_code, error_code, headers_as

IT = "it@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"
OVERDUE_TAGS = ["PC-0019", "SP-0041", "TB-0053"]


def asset_by_tag(db: Session, tag: str) -> Asset:
    db.expire_all()
    return db.scalars(select(Asset).where(Asset.asset_tag == tag)).one()


def loan_for(db: Session, tag: str) -> DeviceLoan:
    db.expire_all()
    return db.scalars(
        select(DeviceLoan)
        .join(Asset, Asset.id == DeviceLoan.asset_id)
        .where(Asset.asset_tag == tag)
        .order_by(DeviceLoan.id.desc())
    ).first()


def first_ready(db: Session) -> Asset:
    db.expire_all()
    return db.scalars(select(Asset).where(Asset.status == "ready").order_by(Asset.id)).first()


def in_days(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def loans(client: TestClient, db: Session, query: str = "", email: str = IT) -> dict:
    response = client.get(f"/api/loans?limit=200{query}", headers=headers_as(db, email))
    assert response.status_code == 200
    return response.json()


def tags(page: dict) -> list[str]:
    return [loan["asset"]["asset_tag"] for loan in page["items"]]


def lend(client: TestClient, db: Session, **body: object) -> object:
    return client.post("/api/loans", json=body, headers=headers_as(db, IT))


def give_back(client: TestClient, db: Session, loan_id: int, **body: object) -> object:
    return client.post(f"/api/loans/{loan_id}/return", json=body, headers=headers_as(db, IT))


def audit_actions(db: Session, entity: str, entity_id: int) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == entity, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.id)
        )
    )


# Access


def test_loans_require_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/loans").status_code == 401


def test_employees_cannot_see_loans(client: TestClient, db: Session) -> None:
    assert client.get("/api/loans", headers=headers_as(db, EMPLOYEE)).status_code == 403


@pytest.mark.parametrize("email", [MANAGER, EMPLOYEE])
def test_only_it_staff_can_lend_or_return(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    body = {"asset_id": first_ready(db).id, "employee_id": 1, "due_at": in_days(7)}
    assert client.post("/api/loans", json=body, headers=headers).status_code == 403
    open_loan = loan_for(db, "TB-0052")
    response = client.post(
        f"/api/loans/{open_loan.id}/return", json={"condition": "ok"}, headers=headers
    )
    assert response.status_code == 403
    assert loan_for(db, "TB-0052").returned_at is None


def test_manager_sees_loans_of_their_department_only(client: TestClient, db: Session) -> None:
    """Part B.2: managers read loans of employees in their own department."""
    page = loans(client, db, email=MANAGER)
    assert sorted(tags(page)) == ["PC-0019", "SP-0043"]
    assert {loan["employee"]["department"] for loan in page["items"]} == {"営業部"}
    assert (
        loans(client, db, "&employee_id=" + str(employee_by_code(db, "E0014").id), MANAGER)["total"]
        == 0
    )


def test_manager_without_employee_link_sees_no_loans(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == MANAGER).values(employee_id=None))
    db.commit()
    assert loans(client, db, email=MANAGER)["total"] == 0


# Listing and overdue


def test_it_admin_sees_all_loans_open_first(client: TestClient, db: Session) -> None:
    page = loans(client, db)
    assert page["total"] == 8
    listed = tags(page)
    assert listed[:4] == ["PC-0019", "SP-0041", "TB-0053", "TB-0052"]
    assert all(loan["returned_at"] for loan in page["items"][4:])


def test_overdue_filter_and_flag(client: TestClient, db: Session) -> None:
    overdue = loans(client, db, "&overdue=true")
    assert sorted(tags(overdue)) == OVERDUE_TAGS
    assert all(loan["is_overdue"] for loan in overdue["items"])
    others = loans(client, db, "&overdue=false")
    assert others["total"] == 5
    assert not any(loan["is_overdue"] for loan in others["items"])


def test_overdue_rule_in_code() -> None:
    """Overdue means: due date passed and not returned. Exactly at the due time is not overdue."""
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    loan = DeviceLoan(due_at=now - timedelta(seconds=1), returned_at=None)
    assert loan_service.is_overdue(loan, now)
    loan.returned_at = now
    assert not loan_service.is_overdue(loan, now)
    assert not loan_service.is_overdue(DeviceLoan(due_at=now, returned_at=None), now)


@pytest.mark.parametrize(("state", "count"), [("open", 4), ("returned", 4)])
def test_state_filter(client: TestClient, db: Session, state: str, count: int) -> None:
    assert loans(client, db, f"&state={state}")["total"] == count


def test_filter_by_employee_and_asset(client: TestClient, db: Session) -> None:
    borrower = employee_by_code(db, "E0011")
    assert tags(loans(client, db, f"&employee_id={borrower.id}")) == ["PC-0019"]
    device = asset_by_tag(db, "PC-0022")
    page = loans(client, db, f"&asset_id={device.id}")
    assert page["items"][0]["wipe_done"] is True
    assert page["items"][0]["condition"] == "ok"


# Lending


def test_lend_a_ready_device(client: TestClient, db: Session) -> None:
    device = first_ready(db)
    borrower = employee_by_code(db, "E0012")
    response = lend(
        client, db, asset_id=device.id, employee_id=borrower.id, due_at=in_days(7), note="出張用"
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["asset"]["asset_tag"], body["employee"]["employee_code"]) == (
        device.asset_tag,
        "E0012",
    )
    assert body["returned_at"] is None and body["is_overdue"] is False
    assert body["lent_by"] == db.scalar(select(User.id).where(User.email == IT))

    lent = asset_by_tag(db, device.asset_tag)
    assert (lent.status, lent.assigned_to) == ("on_loan", borrower.id)
    assert audit_actions(db, "loan", body["id"]) == ["LOAN_CREATED"]
    assert audit_actions(db, "asset", device.id) == ["ASSET_STATUS_CHANGED"]


def test_due_date_must_be_in_the_future(client: TestClient, db: Session) -> None:
    device = first_ready(db)
    response = lend(client, db, asset_id=device.id, employee_id=1, due_at=in_days(-1))
    assert error_code(response) == "DUE_DATE_IN_PAST"
    assert asset_by_tag(db, device.asset_tag).status == "ready"


def test_due_date_needs_a_timezone(client: TestClient, db: Session) -> None:
    response = lend(
        client, db, asset_id=first_ready(db).id, employee_id=1, due_at="2030-01-01T10:00:00"
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("asset_status", "employee_code", "code"),
    [
        ("assigned", "E0012", "INVALID_STATUS_CHANGE"),
        ("on_loan", "E0012", "INVALID_STATUS_CHANGE"),
        ("in_stock", "E0012", "INVALID_STATUS_CHANGE"),
        ("ready", "E0016", "EMPLOYEE_NOT_ACTIVE"),
        ("ready", "E0029", "EMPLOYEE_NOT_ACTIVE"),
    ],
)
def test_lending_rules(
    client: TestClient, db: Session, asset_status: str, employee_code: str, code: str
) -> None:
    device = db.scalars(
        select(Asset).where(Asset.status == asset_status).order_by(Asset.id)
    ).first()
    before = db.scalar(select(func.count()).select_from(DeviceLoan))
    response = lend(
        client,
        db,
        asset_id=device.id,
        employee_id=employee_by_code(db, employee_code).id,
        due_at=in_days(7),
    )
    assert response.status_code == 400
    assert error_code(response) == code
    assert db.scalar(select(func.count()).select_from(DeviceLoan)) == before


def test_lending_unknown_device_or_employee(client: TestClient, db: Session) -> None:
    assert lend(client, db, asset_id=999999, employee_id=1, due_at=in_days(3)).status_code == 404
    response = lend(client, db, asset_id=first_ready(db).id, employee_id=999999, due_at=in_days(3))
    assert error_code(response) == "EMPLOYEE_NOT_FOUND"


# Returning


def test_return_without_wipe_goes_to_returned(client: TestClient, db: Session) -> None:
    open_loan = loan_for(db, "PC-0019")
    response = give_back(client, db, open_loan.id, condition="ok", note="Charger included")
    assert response.status_code == 200
    body = response.json()
    assert body["returned_at"] is not None
    assert (body["condition"], body["wipe_done"], body["is_overdue"]) == ("ok", False, False)
    assert body["note"] == "Charger included"

    device = asset_by_tag(db, "PC-0019")
    assert (device.status, device.assigned_to) == ("returned", None)
    assert audit_actions(db, "loan", open_loan.id) == ["LOAN_RETURNED"]
    assert "PC-0019" not in tags(loans(client, db, "&overdue=true"))


def test_return_with_wipe_goes_to_wiped(client: TestClient, db: Session) -> None:
    open_loan = loan_for(db, "SP-0041")
    body = give_back(client, db, open_loan.id, condition="damaged", wipe_done=True).json()
    assert (body["condition"], body["wipe_done"]) == ("damaged", True)

    device = asset_by_tag(db, "SP-0041")
    assert (device.status, device.assigned_to) == ("wiped", None)
    history = client.get(f"/api/assets/{device.id}/history", headers=headers_as(db, IT)).json()
    assert [h["detail"].get("new_status") for h in history] == ["returned", "wiped"]
    assert history[-1]["detail"]["wipe_confirmed"] is True


def test_a_loan_can_be_returned_only_once(client: TestClient, db: Session) -> None:
    open_loan = loan_for(db, "TB-0052")
    assert give_back(client, db, open_loan.id, condition="ok").status_code == 200
    again = give_back(client, db, open_loan.id, condition="ok", wipe_done=True)
    assert again.status_code == 400
    assert error_code(again) == "LOAN_ALREADY_RETURNED"
    assert audit_actions(db, "loan", open_loan.id) == ["LOAN_RETURNED"]
    assert asset_by_tag(db, "TB-0052").status == "returned"


@pytest.mark.parametrize("body", [{}, {"condition": "lost"}, {"condition": "ok", "extra": 1}])
def test_return_validation(client: TestClient, db: Session, body: dict) -> None:
    open_loan = loan_for(db, "TB-0052")
    assert give_back(client, db, open_loan.id, **body).status_code == 422
    assert loan_for(db, "TB-0052").returned_at is None


def test_return_unknown_loan_is_404(client: TestClient, db: Session) -> None:
    response = give_back(client, db, 999999, condition="ok")
    assert error_code(response) == "LOAN_NOT_FOUND"


def test_device_on_open_loan_cannot_be_retired(client: TestClient, db: Session) -> None:
    device = asset_by_tag(db, "TB-0053")
    response = client.post(
        f"/api/assets/{device.id}/status",
        json={"new_status": "retired", "note": "Lost by user"},
        headers=headers_as(db, IT),
    )
    assert error_code(response) == "OPEN_LOAN_EXISTS"


def test_failed_audit_rolls_back_the_return(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_loan = loan_for(db, "TB-0052")
    original = audit_service.record

    def fail_on_loan_returned(*args: object, **kwargs: object) -> object:
        if args[2] == "LOAN_RETURNED":
            raise RuntimeError("audit storage failed")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(audit_service, "record", fail_on_loan_returned)
    assert give_back(client, db, open_loan.id, condition="ok").status_code == 500
    assert loan_for(db, "TB-0052").returned_at is None
    assert asset_by_tag(db, "TB-0052").status == "on_loan"


def test_simultaneous_returns_give_one_winner(test_engine: Engine, db: Session) -> None:
    loan_id = loan_for(db, "TB-0052").id
    actor_id = db.scalar(select(User.id).where(User.email == IT))
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt() -> None:
        with Session(test_engine) as session:
            actor = session.get(User, actor_id)
            barrier.wait()
            try:
                loan_service.return_loan(session, loan_id, "ok", False, None, actor)
                session.commit()
                results.append("ok")
            except AppError as exc:
                session.rollback()
                results.append(exc.code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == ["LOAN_ALREADY_RETURNED", "ok"]
    assert audit_actions(db, "loan", loan_id) == ["LOAN_RETURNED"]


# Employee departure flow


def held(client: TestClient, db: Session, code: str, email: str = IT) -> object:
    employee = employee_by_code(db, code)
    return client.get(f"/api/employees/{employee.id}/devices", headers=headers_as(db, email))


def test_held_devices_lists_assigned_devices(client: TestClient, db: Session) -> None:
    response = held(client, db, "E0010")
    assert response.status_code == 200
    devices = response.json()
    assert [d["asset_tag"] for d in devices] == ["PC-0001", "SP-0026"]
    assert all(d["status"] == "assigned" and d["open_loan"] is None for d in devices)
    assert devices[0]["os"] == "Windows 11 Pro"


def test_held_devices_include_loans_with_overdue_flag(client: TestClient, db: Session) -> None:
    devices = {d["asset_tag"]: d for d in held(client, db, "E0011").json()}
    loaned = devices["PC-0019"]
    assert loaned["status"] == "on_loan"
    assert loaned["open_loan"]["id"] == loan_for(db, "PC-0019").id
    assert loaned["open_loan"]["is_overdue"] is True


def test_held_devices_include_devices_in_repair(client: TestClient, db: Session) -> None:
    """A device in repair keeps its holder (approved decision), so it is still listed."""
    repair = db.scalars(select(Asset).where(Asset.status == "repair").order_by(Asset.id)).first()
    holder = db.get(Employee, repair.assigned_to)
    devices = held(client, db, holder.employee_code).json()
    assert repair.asset_tag in [d["asset_tag"] for d in devices]


def test_held_devices_scope(client: TestClient, db: Session) -> None:
    assert held(client, db, "E0011", MANAGER).status_code == 200
    other = held(client, db, "E0001", MANAGER)
    assert other.status_code == 404
    assert held(client, db, "E0010", EMPLOYEE).status_code == 403
    missing = client.get("/api/employees/999999/devices", headers=headers_as(db, IT))
    assert missing.status_code == 404


def test_departure_does_not_return_devices_or_close_loans(client: TestClient, db: Session) -> None:
    """Marking an employee left keeps every device, loan, and history row in place."""
    leaver = employee_by_code(db, "E0011")
    before = [d["asset_tag"] for d in held(client, db, "E0011").json()]
    response = client.delete(f"/api/employees/{leaver.id}", headers=headers_as(db, IT))
    assert response.json()["status"] == "left"

    assert [d["asset_tag"] for d in held(client, db, "E0011").json()] == before
    assert loan_for(db, "PC-0019").returned_at is None
    assert "PC-0019" in tags(loans(client, db, "&overdue=true"))


def test_full_leaver_flow(client: TestClient, db: Session) -> None:
    """Mark left, list held devices, return each one the right way, end with nothing held."""
    headers = headers_as(db, IT)
    leaver = employee_by_code(db, "E0011")
    client.delete(f"/api/employees/{leaver.id}", headers=headers)

    for device in held(client, db, "E0011").json():
        if device["open_loan"]:
            response = give_back(client, db, device["open_loan"]["id"], condition="ok")
        elif device["status"] == "assigned":
            response = client.post(
                f"/api/assets/{device['id']}/status",
                json={"new_status": "returned"},
                headers=headers,
            )
        else:  # in repair: back to ready clears the holder
            response = client.post(
                f"/api/assets/{device['id']}/status", json={"new_status": "ready"}, headers=headers
            )
        assert response.status_code == 200, device

    assert held(client, db, "E0011").json() == []
    # The returned loan stays in the history after departure.
    history = loans(client, db, f"&employee_id={leaver.id}")
    assert history["total"] == 1 and history["items"][0]["returned_at"] is not None
