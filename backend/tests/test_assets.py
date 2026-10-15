"""Phase 5 tests: asset API, role scoping, device details, status endpoint, and history.

Seed facts used here: 60 devices. employee@demo (E0010, 営業部) holds PC-0001 and an
iPhone. manager@demo sees only devices held in 営業部. E0016 is on leave.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, AuditLog, DeviceDetail, DeviceLoan, Employee, KittingTask, User
from app.services import audit_service
from tests.helpers import employee_by_code, error_code, headers_as

IT = "it@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"

NEW_ASSET = {
    "asset_tag": "PC-9001",
    "type": "laptop",
    "serial_number": "NEW-SERIAL-9001",
    "manufacturer": "Dell",
    "model": "Latitude 7450",
    "purchase_date": "2026-10-01",
    "warranty_end": "2029-09-30",
    "cost": "215000",
    "location": "本社 IT倉庫",
}


def asset_by_tag(db: Session, tag: str) -> Asset:
    db.expire_all()
    return db.scalars(select(Asset).where(Asset.asset_tag == tag)).one()


def first_asset(db: Session, status: str) -> Asset:
    db.expire_all()
    return db.scalars(select(Asset).where(Asset.status == status).order_by(Asset.id)).first()


def held_by(db: Session, code: str) -> list[str]:
    employee = employee_by_code(db, code)
    return sorted(db.scalars(select(Asset.asset_tag).where(Asset.assigned_to == employee.id)))


def set_status(client: TestClient, db: Session, asset: Asset, **body: object) -> object:
    return client.post(f"/api/assets/{asset.id}/status", json=body, headers=headers_as(db, IT))


def list_tags(client: TestClient, headers: dict, query: str = "") -> list[str]:
    response = client.get(f"/api/assets?limit=200{query}", headers=headers)
    assert response.status_code == 200
    return [a["asset_tag"] for a in response.json()["items"]]


# Seed consistency


def test_seeded_devices_are_consistent(db: Session) -> None:
    counts = dict(db.execute(select(Asset.type, func.count()).group_by(Asset.type)).all())
    assert counts == {"laptop": 25, "smartphone": 20, "tablet": 10, "monitor": 5}
    assert db.scalar(select(func.count()).select_from(DeviceDetail)) == 60
    inactive_holders = db.scalar(
        select(func.count())
        .select_from(Asset)
        .join(Employee, Employee.id == Asset.assigned_to)
        .where(Employee.status != "active")
    )
    assert inactive_holders == 0
    assert len(held_by(db, "E0010")) == 2


# Access by role


def test_asset_endpoints_require_login(client: TestClient, db: Session) -> None:
    assert client.get("/api/assets").status_code == 401
    assert client.get("/api/assets/1").status_code == 401


@pytest.mark.parametrize("email", [MANAGER, EMPLOYEE])
def test_only_it_staff_can_write(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    own = asset_by_tag(db, "PC-0001")
    assert client.post("/api/assets", json=NEW_ASSET, headers=headers).status_code == 403
    assert (
        client.put(f"/api/assets/{own.id}", json={"location": "x"}, headers=headers).status_code
        == 403
    )
    assert (
        client.put(f"/api/assets/{own.id}/details", json={"os": "x"}, headers=headers).status_code
        == 403
    )
    response = client.post(
        f"/api/assets/{own.id}/status", json={"new_status": "returned"}, headers=headers
    )
    assert response.status_code == 403
    assert asset_by_tag(db, "PC-0001").status == "assigned"


def test_it_admin_sees_every_device(client: TestClient, db: Session) -> None:
    assert len(list_tags(client, headers_as(db, IT))) == 60


def test_employee_sees_only_their_own_devices(client: TestClient, db: Session) -> None:
    """Approved decision: employees have read-only access to devices they hold."""
    headers = headers_as(db, EMPLOYEE)
    assert sorted(list_tags(client, headers)) == held_by(db, "E0010")
    other = asset_by_tag(db, "PC-0002")
    assert client.get(f"/api/assets/{other.id}", headers=headers).status_code == 404
    own = asset_by_tag(db, "PC-0001")
    body = client.get(f"/api/assets/{own.id}", headers=headers).json()
    assert body["asset_tag"] == "PC-0001"
    assert body["allowed_transitions"] == []
    assert client.get(f"/api/assets/{own.id}/details", headers=headers).status_code == 200


def test_employee_cannot_read_device_history(client: TestClient, db: Session) -> None:
    own = asset_by_tag(db, "PC-0001")
    response = client.get(f"/api/assets/{own.id}/history", headers=headers_as(db, EMPLOYEE))
    assert response.status_code == 403


def test_manager_sees_only_devices_held_in_their_department(
    client: TestClient, db: Session
) -> None:
    """Part B.2: stock and unheld devices are hidden from managers."""
    response = client.get("/api/assets?limit=200", headers=headers_as(db, MANAGER))
    items = response.json()["items"]
    assert items, "the seed gives 営業部 some devices"
    assert {a["holder"]["department"] for a in items} == {"営業部"}
    assert {a["status"] for a in items} <= {"assigned", "on_loan", "repair"}
    expected = db.scalar(
        select(func.count())
        .select_from(Asset)
        .join(Employee, Employee.id == Asset.assigned_to)
        .where(Employee.department == "営業部")
    )
    assert response.json()["total"] == expected


def test_manager_gets_404_for_stock_and_other_departments(client: TestClient, db: Session) -> None:
    headers = headers_as(db, MANAGER)
    stock = first_asset(db, "in_stock")
    assert client.get(f"/api/assets/{stock.id}", headers=headers).status_code == 404
    other_department = db.scalars(
        select(Asset)
        .join(Employee, Employee.id == Asset.assigned_to)
        .where(Employee.department == "情報システム部")
    ).first()
    response = client.get(f"/api/assets/{other_department.id}/history", headers=headers)
    assert response.status_code == 404
    assert error_code(response) == "ASSET_NOT_FOUND"


def test_manager_department_filter_cannot_widen_scope(client: TestClient, db: Session) -> None:
    tags = list_tags(client, headers_as(db, MANAGER), "&department=情報システム部")
    assert tags == []


def test_manager_without_employee_link_sees_nothing(client: TestClient, db: Session) -> None:
    manager = db.scalars(select(User).where(User.email == MANAGER)).one()
    manager.employee_id = None
    db.commit()
    assert list_tags(client, headers_as(db, MANAGER)) == []


# Filters and search


def test_filters(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    assert len(list_tags(client, headers, "&type=tablet")) == 10
    assert len(list_tags(client, headers, "&status=retired")) == 2
    assert len(list_tags(client, headers, "&os=iOS")) == len(
        db.scalars(select(DeviceDetail).where(DeviceDetail.os == "iOS")).all()
    )
    non_compliant = list_tags(client, headers, "&compliance=non_compliant")
    assert non_compliant and len(non_compliant) == db.scalar(
        select(func.count())
        .select_from(DeviceDetail)
        .where(DeviceDetail.compliance == "non_compliant")
    )
    sales = list_tags(client, headers, "&department=営業部")
    assert sorted(sales) == sorted(list_tags(client, headers_as(db, MANAGER)))


def test_search_by_serial_imei_phone_and_holder_name(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    phone_asset = db.scalars(
        select(Asset).where(Asset.type == "smartphone").order_by(Asset.id)
    ).first()
    details = db.get(DeviceDetail, phone_asset.id)
    assert list_tags(client, headers, f"&q={phone_asset.serial_number}") == [phone_asset.asset_tag]
    assert phone_asset.asset_tag in list_tags(client, headers, f"&q={details.imei}")
    assert phone_asset.asset_tag in list_tags(client, headers, f"&q={details.phone_number}")
    by_name = list_tags(client, headers, "&q=加藤")  # 加藤 さくら is E0010
    assert sorted(by_name) == held_by(db, "E0010")


def test_overdue_filter(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    assert list_tags(client, headers, "&overdue=true") == []

    asset = first_asset(db, "ready")
    borrower = employee_by_code(db, "E0003")
    it_user = db.scalars(select(User).where(User.email == IT)).one()
    asset.status, asset.assigned_to = "on_loan", borrower.id
    now = datetime.now(UTC)
    db.add(
        DeviceLoan(
            asset_id=asset.id,
            employee_id=borrower.id,
            lent_by=it_user.id,
            lent_at=now - timedelta(days=10),
            due_at=now - timedelta(days=3),
        )
    )
    db.commit()
    assert list_tags(client, headers, "&overdue=true") == [asset.asset_tag]
    assert asset.asset_tag not in list_tags(client, headers, "&overdue=false")


# Create and update


def test_create_asset_with_empty_details(client: TestClient, db: Session) -> None:
    response = client.post("/api/assets", json=NEW_ASSET, headers=headers_as(db, IT))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ordered"
    assert body["holder"] is None
    assert body["details"]["compliance"] == "unknown"
    assert body["allowed_transitions"] == ["in_stock", "retired"]
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "ASSET_CREATED")).one()
    assert entry.detail == {"asset_tag": "PC-9001", "type": "laptop", "status": "ordered"}


def test_create_asset_in_stock(client: TestClient, db: Session) -> None:
    body = {**NEW_ASSET, "status": "in_stock"}
    assert client.post("/api/assets", json=body, headers=headers_as(db, IT)).json()["status"] == (
        "in_stock"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "assigned"},
        {"assigned_to": 1},
        {"type": "server"},
        {"cost": "-1"},
        {"asset_tag": ""},
        {"asset_tag": "x" * 31},
        {"warranty_end": "2026-01-01"},
    ],
    ids=["status", "holder", "type", "cost", "empty-tag", "long-tag", "warranty"],
)
def test_create_validation(client: TestClient, db: Session, change: dict) -> None:
    response = client.post("/api/assets", json={**NEW_ASSET, **change}, headers=headers_as(db, IT))
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"asset_tag": "PC-0001"}, "ASSET_TAG_EXISTS"),
        ({"serial_number": "DL5440000001"}, "SERIAL_NUMBER_EXISTS"),
    ],
)
def test_create_rejects_duplicates(
    client: TestClient, db: Session, change: dict, code: str
) -> None:
    response = client.post("/api/assets", json={**NEW_ASSET, **change}, headers=headers_as(db, IT))
    assert response.status_code == 400
    assert error_code(response) == code


def test_update_asset_fields_and_audit(client: TestClient, db: Session) -> None:
    asset = asset_by_tag(db, "PC-0002")
    response = client.put(
        f"/api/assets/{asset.id}",
        json={"location": "大阪支社", "cost": "150000.50"},
        headers=headers_as(db, IT),
    )
    assert response.status_code == 200
    assert response.json()["location"] == "大阪支社"
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "ASSET_UPDATED")).one()
    assert entry.detail["location"]["new"] == "大阪支社"
    assert entry.detail["cost"]["new"] == "150000.50"


@pytest.mark.parametrize("body", [{"status": "retired"}, {"assigned_to": 3}, {"asset_tag": None}])
def test_update_cannot_touch_status_or_holder(client: TestClient, db: Session, body: dict) -> None:
    asset = asset_by_tag(db, "PC-0002")
    response = client.put(f"/api/assets/{asset.id}", json=body, headers=headers_as(db, IT))
    assert response.status_code == 422


def test_update_checks_warranty_against_stored_purchase_date(
    client: TestClient, db: Session
) -> None:
    asset = asset_by_tag(db, "PC-0002")
    too_early = (asset.purchase_date - timedelta(days=1)).isoformat()
    response = client.put(
        f"/api/assets/{asset.id}", json={"warranty_end": too_early}, headers=headers_as(db, IT)
    )
    assert error_code(response) == "WARRANTY_BEFORE_PURCHASE"


def test_update_rejects_another_assets_serial(client: TestClient, db: Session) -> None:
    asset = asset_by_tag(db, "PC-0002")
    other = asset_by_tag(db, "PC-0003")
    response = client.put(
        f"/api/assets/{asset.id}",
        json={"serial_number": other.serial_number},
        headers=headers_as(db, IT),
    )
    assert error_code(response) == "SERIAL_NUMBER_EXISTS"


def test_update_unknown_asset_is_404(client: TestClient, db: Session) -> None:
    response = client.put("/api/assets/999999", json={"location": "x"}, headers=headers_as(db, IT))
    assert response.status_code == 404


# Device details


def test_update_details_appears_in_history(client: TestClient, db: Session) -> None:
    asset = asset_by_tag(db, "PC-0002")
    headers = headers_as(db, IT)
    response = client.put(
        f"/api/assets/{asset.id}/details",
        json={"compliance": "non_compliant", "os_version": "24H2", "mac_address": None},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["compliance"], body["os_version"], body["mac_address"]) == (
        "non_compliant",
        "24H2",
        None,
    )
    history = client.get(f"/api/assets/{asset.id}/history", headers=headers).json()
    assert [h["action"] for h in history] == ["DEVICE_DETAILS_UPDATED"]
    assert history[0]["actor_email"] == IT


@pytest.mark.parametrize(
    "body",
    [
        {"mac_address": "zz:zz"},
        {"imei": "12ab"},
        {"sim_iccid": "123"},
        {"compliance": "maybe"},
        {"ram_gb": -1},
        {"mdm_enrolled": None},
    ],
)
def test_details_validation(client: TestClient, db: Session, body: dict) -> None:
    asset = asset_by_tag(db, "PC-0002")
    response = client.put(f"/api/assets/{asset.id}/details", json=body, headers=headers_as(db, IT))
    assert response.status_code == 422


# Status endpoint


def test_full_lifecycle_through_the_api(client: TestClient, db: Session) -> None:
    """in_stock -> kitting -> ready -> assigned -> repair -> ready -> assigned -> returned
    -> wiped -> in_stock, with the history recording each step in order."""
    asset = first_asset(db, "in_stock")
    employee = employee_by_code(db, "E0011")

    assert set_status(client, db, asset, new_status="kitting").status_code == 200
    blocked = set_status(client, db, asset, new_status="ready")
    assert error_code(blocked) == "KITTING_NOT_COMPLETE"
    db.add(
        KittingTask(
            asset_id=asset.id,
            step_no=1,
            step_en="Enroll",
            step_ja="登録",
            done=True,
            done_at=datetime.now(UTC),
        )
    )
    db.commit()

    steps = [
        {"new_status": "ready"},
        {"new_status": "assigned", "employee_id": employee.id},
        {"new_status": "repair", "note": "Screen flicker"},
        {"new_status": "ready"},
        {"new_status": "assigned", "employee_id": employee.id},
        {"new_status": "returned"},
        {"new_status": "wiped", "wipe_confirmed": True},
        {"new_status": "in_stock"},
    ]
    for step in steps:
        response = set_status(client, db, asset, **step)
        assert response.status_code == 200, (step, response.json())
        assert response.json()["status"] == step["new_status"]

    history = client.get(f"/api/assets/{asset.id}/history", headers=headers_as(db, IT)).json()
    assert [h["detail"]["new_status"] for h in history] == [
        "kitting",
        "ready",
        "assigned",
        "repair",
        "ready",
        "assigned",
        "returned",
        "wiped",
        "in_stock",
    ]
    assert all(h["actor_email"] == IT for h in history)


def test_repeated_request_is_refused_the_second_time(client: TestClient, db: Session) -> None:
    asset = first_asset(db, "ordered")
    assert set_status(client, db, asset, new_status="in_stock").status_code == 200
    again = set_status(client, db, asset, new_status="in_stock")
    assert again.status_code == 400
    assert error_code(again) == "INVALID_STATUS_CHANGE"
    actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_id == asset.id)).all()
    assert actions == ["ASSET_STATUS_CHANGED"]


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        ("ready", {"new_status": "assigned"}, "EMPLOYEE_REQUIRED"),
        ("ready", {"new_status": "on_loan", "employee_id": 1}, "LOAN_WORKFLOW_REQUIRED"),
        ("returned", {"new_status": "wiped"}, "WIPE_CONFIRMATION_REQUIRED"),
        ("in_stock", {"new_status": "retired"}, "RETIREMENT_NOTE_REQUIRED"),
        ("in_stock", {"new_status": "assigned", "employee_id": 1}, "INVALID_STATUS_CHANGE"),
        ("retired", {"new_status": "in_stock"}, "INVALID_STATUS_CHANGE"),
    ],
)
def test_rule_violations_return_400_with_the_right_code(
    client: TestClient, db: Session, status: str, body: dict, code: str
) -> None:
    asset = first_asset(db, status)
    response = set_status(client, db, asset, **body)
    assert response.status_code == 400
    assert error_code(response) == code
    assert asset_by_tag(db, asset.asset_tag).status == status


def test_assigning_to_someone_on_leave_is_refused(client: TestClient, db: Session) -> None:
    asset = first_asset(db, "ready")
    on_leave = employee_by_code(db, "E0016")
    response = set_status(client, db, asset, new_status="assigned", employee_id=on_leave.id)
    assert error_code(response) == "EMPLOYEE_NOT_ACTIVE"


def test_unknown_status_value_is_422(client: TestClient, db: Session) -> None:
    asset = first_asset(db, "ready")
    assert set_status(client, db, asset, new_status="lost").status_code == 422


def test_allowed_transitions_follow_the_status(client: TestClient, db: Session) -> None:
    asset = first_asset(db, "assigned")
    body = client.get(f"/api/assets/{asset.id}", headers=headers_as(db, IT)).json()
    assert body["allowed_transitions"] == ["returned", "repair", "retired"]


def test_failed_audit_rolls_back_the_status_change(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = first_asset(db, "ordered")

    def broken_record(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(audit_service, "record", broken_record)
    response = set_status(client, db, asset, new_status="in_stock")
    assert response.status_code == 500
    assert asset_by_tag(db, asset.asset_tag).status == "ordered"
