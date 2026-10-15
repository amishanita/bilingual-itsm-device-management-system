"""Phase 9 tests: the dashboard summary and its per-role scoping."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Asset, DeviceDetail, Employee, Ticket, User
from app.models.base import ASSET_STATUSES, ASSET_TYPES, TICKET_CATEGORIES, TICKET_PRIORITIES
from app.services import loan_service
from tests.helpers import error_code, headers_as

IT = "it@demo"
MANAGER = "manager@demo"


def summary(client: TestClient, db: Session, email: str = IT) -> dict:
    response = client.get("/api/dashboard/summary", headers=headers_as(db, email))
    assert response.status_code == 200
    return response.json()


def test_dashboard_requires_staff(client: TestClient, db: Session) -> None:
    assert client.get("/api/dashboard/summary").status_code == 401
    response = client.get("/api/dashboard/summary", headers=headers_as(db, "employee@demo"))
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_device_counts(client: TestClient, db: Session) -> None:
    body = summary(client, db)
    assert list(body["devices_by_type"]) == list(ASSET_TYPES)
    assert body["devices_by_type"] == {
        "laptop": 24,
        "desktop": 0,
        "smartphone": 19,
        "tablet": 10,
        "monitor": 5,
        "printer": 0,
    }, "retired devices are left out of the active fleet"
    assert body["total_devices"] == 58
    assert list(body["devices_by_status"]) == list(ASSET_STATUSES)
    assert sum(body["devices_by_status"].values()) == 60
    assert body["devices_by_status"]["retired"] == 2


def test_kitting_overdue_and_compliance(client: TestClient, db: Session) -> None:
    body = summary(client, db)
    assert {k["asset_tag"]: k["percent"] for k in body["kitting"]} == {
        "PC-0016": 43,
        "PC-0017": 86,
        "SP-0039": 33,
        "TB-0051": 17,
    }
    assert body["overdue_loans"] == 3
    expected_non_compliant = db.scalar(
        select(func.count())
        .select_from(DeviceDetail)
        .join(Asset, Asset.id == DeviceDetail.asset_id)
        .where(DeviceDetail.compliance == "non_compliant", Asset.status != "retired")
    )
    assert body["non_compliant_devices"] == expected_non_compliant > 0


def test_warranties_ending_within_60_days(client: TestClient, db: Session) -> None:
    body = summary(client, db)
    today = loan_service.now_utc().date()
    expected = list(
        db.scalars(
            select(Asset.asset_tag)
            .where(
                Asset.status != "retired",
                Asset.warranty_end >= today,
                Asset.warranty_end <= today + timedelta(days=60),
            )
            .order_by(Asset.warranty_end, Asset.asset_tag)
        )
    )
    assert body["warranty_window_days"] == 60
    assert [w["asset_tag"] for w in body["warranties_ending"]] == expected
    assert expected, "the seed places some warranties inside the window"


def test_open_tickets(client: TestClient, db: Session) -> None:
    body = summary(client, db)
    assert body["open_tickets"] == 40, "20 open + 20 in progress"
    assert list(body["open_tickets_by_priority"]) == list(TICKET_PRIORITIES)
    assert list(body["open_tickets_by_category"]) == list(TICKET_CATEGORIES)
    assert sum(body["open_tickets_by_priority"].values()) == 40
    assert sum(body["open_tickets_by_category"].values()) == 40


def test_manager_dashboard_is_limited_to_their_department(client: TestClient, db: Session) -> None:
    """Part B.2: the manager's dashboard covers 営業部 only."""
    body = summary(client, db, MANAGER)
    held_in_sales = db.scalar(
        select(func.count())
        .select_from(Asset)
        .join(Employee, Employee.id == Asset.assigned_to)
        .where(Employee.department == "営業部")
    )
    assert sum(body["devices_by_status"].values()) == held_in_sales
    assert body["kitting"] == [], "devices in kitting are not held by anyone"
    assert body["overdue_loans"] == 1, "only PC-0019 (E0011) is in 営業部"
    open_in_sales = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .join(Employee, Employee.id == Ticket.requester_id)
        .where(Employee.department == "営業部", Ticket.status.in_(("open", "in_progress")))
    )
    assert body["open_tickets"] == open_in_sales


def test_manager_without_employee_link_gets_zeros(client: TestClient, db: Session) -> None:
    db.execute(update(User).where(User.email == MANAGER).values(employee_id=None))
    db.commit()
    body = summary(client, db, MANAGER)
    assert body["total_devices"] == 0 and body["open_tickets"] == 0
    assert body["overdue_loans"] == 0 and body["warranties_ending"] == []


def test_dashboard_follows_changes(client: TestClient, db: Session) -> None:
    loan_page = client.get("/api/loans?overdue=true", headers=headers_as(db, IT)).json()
    loan_id = loan_page["items"][0]["id"]
    client.post(
        f"/api/loans/{loan_id}/return", json={"condition": "ok"}, headers=headers_as(db, IT)
    )
    assert summary(client, db)["overdue_loans"] == 2
