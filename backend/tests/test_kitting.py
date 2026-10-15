"""Phase 6 tests: kitting templates, starting a run, ticking steps, re-kits, and the board.

Seed facts used here: four templates (one laptop, two smartphone, one tablet).
In kitting: PC-0016 (3/7, it@demo), PC-0017 (6/7, admin@demo), SP-0039 iPhone (2/6,
it@demo), TB-0051 tablet on run 2 (1/6, admin@demo) with a finished run 1.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, AuditLog, KittingTask, KittingTemplate
from app.services import audit_service
from tests.helpers import error_code, headers_as

IT = "it@demo"
MANAGER = "manager@demo"
EMPLOYEE = "employee@demo"

NEW_TEMPLATE = {
    "device_type": "desktop",
    "name": "Desktop PC",
    "steps": [
        {"en": "Image the disk", "ja": "ディスクにイメージを展開する"},
        {"en": "Join the domain", "ja": "ドメインに参加する"},
    ],
}


def asset_by_tag(db: Session, tag: str) -> Asset:
    db.expire_all()
    return db.scalars(select(Asset).where(Asset.asset_tag == tag)).one()


def first_in_stock(db: Session, asset_type: str, model_prefix: str = "") -> Asset:
    db.expire_all()
    return db.scalars(
        select(Asset)
        .where(
            Asset.type == asset_type,
            Asset.status == "in_stock",
            Asset.model.startswith(model_prefix),
        )
        .order_by(Asset.id)
    ).first()


def template_id(db: Session, name: str) -> int:
    return db.scalar(select(KittingTemplate.id).where(KittingTemplate.name == name))


def start(client: TestClient, db: Session, asset: Asset, **body: object) -> object:
    return client.post(
        f"/api/assets/{asset.id}/kitting/start", json=body, headers=headers_as(db, IT)
    )


def tick(client: TestClient, db: Session, task_id: int, done: bool = True) -> object:
    return client.patch(
        f"/api/kitting-tasks/{task_id}", json={"done": done}, headers=headers_as(db, IT)
    )


def checklist(client: TestClient, db: Session, asset: Asset, query: str = "") -> dict:
    response = client.get(f"/api/assets/{asset.id}/kitting{query}", headers=headers_as(db, IT))
    assert response.status_code == 200
    return response.json()


def audit_actions(db: Session, asset_id: int) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "asset", AuditLog.entity_id == asset_id)
            .order_by(AuditLog.id)
        )
    )


# Templates


@pytest.mark.parametrize("email", [MANAGER, EMPLOYEE])
def test_templates_are_it_only(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    assert client.get("/api/kitting/templates", headers=headers).status_code == 403
    assert (
        client.post("/api/kitting/templates", json=NEW_TEMPLATE, headers=headers).status_code == 403
    )


def test_list_templates(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    all_templates = client.get("/api/kitting/templates", headers=headers).json()
    assert len(all_templates) == 4
    windows = next(t for t in all_templates if t["device_type"] == "laptop")
    assert windows["steps"][0] == {
        "en": "Register the hardware hash in Windows Autopilot",
        "ja": "ハードウェアハッシュをWindows Autopilotに登録する",
    }
    phones = client.get("/api/kitting/templates?device_type=smartphone", headers=headers).json()
    assert {t["name"] for t in phones} == {"iPhone and iPad", "Android"}


def test_create_template_and_audit(client: TestClient, db: Session) -> None:
    response = client.post("/api/kitting/templates", json=NEW_TEMPLATE, headers=headers_as(db, IT))
    assert response.status_code == 201
    assert len(response.json()["steps"]) == 2
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "KITTING_TEMPLATE_CREATED")).one()
    assert entry.detail == {"device_type": "desktop", "name": "Desktop PC", "steps": 2}


def test_template_names_are_unique_per_device_type(client: TestClient, db: Session) -> None:
    headers = headers_as(db, IT)
    duplicate = {**NEW_TEMPLATE, "device_type": "laptop", "name": "Windows PC (Autopilot / Intune)"}
    response = client.post("/api/kitting/templates", json=duplicate, headers=headers)
    assert error_code(response) == "TEMPLATE_NAME_EXISTS"
    # The same name for another device type is fine.
    other_type = {**duplicate, "device_type": "desktop"}
    assert (
        client.post("/api/kitting/templates", json=other_type, headers=headers).status_code == 201
    )


@pytest.mark.parametrize(
    "change",
    [
        {"steps": []},
        {"steps": [{"en": "Only English"}]},
        {"steps": [{"en": "x" * 201, "ja": "長い"}]},
        {"steps": [{"en": "a", "ja": "b"}] * 51},
        {"device_type": "server"},
        {"name": ""},
        {"steps": [{"en": "a", "ja": "b", "extra": "c"}]},
    ],
    ids=["no-steps", "missing-ja", "long-step", "too-many", "bad-type", "no-name", "extra"],
)
def test_template_validation(client: TestClient, db: Session, change: dict) -> None:
    response = client.post(
        "/api/kitting/templates", json={**NEW_TEMPLATE, **change}, headers=headers_as(db, IT)
    )
    assert response.status_code == 422


# Starting kitting


def test_start_kitting_copies_the_template(client: TestClient, db: Session) -> None:
    laptop = first_in_stock(db, "laptop")
    response = start(client, db, laptop)
    assert response.status_code == 201
    body = response.json()
    assert (body["status"], body["run_no"], body["runs"]) == ("kitting", 1, [1])
    assert (body["done"], body["total"], body["percent"], body["editable"]) == (0, 7, 0, True)
    assert [t["step_no"] for t in body["tasks"]] == list(range(1, 8))
    assert body["tasks"][4]["step_ja"] == "BitLockerによる暗号化が有効か確認する"
    assert asset_by_tag(db, laptop.asset_tag).status == "kitting"
    assert audit_actions(db, laptop.id) == ["ASSET_STATUS_CHANGED", "KITTING_STARTED"]


def test_device_type_with_several_templates_needs_a_choice(client: TestClient, db: Session) -> None:
    pixel = first_in_stock(db, "smartphone", "Pixel")
    assert error_code(start(client, db, pixel)) == "TEMPLATE_REQUIRED"
    response = start(client, db, pixel, template_id=template_id(db, "Android"))
    assert response.status_code == 201
    assert response.json()["total"] == 5


@pytest.mark.parametrize(
    ("asset_type", "template_name", "code"),
    [
        ("laptop", "Android", "TEMPLATE_TYPE_MISMATCH"),
        ("laptop", None, "TEMPLATE_NOT_FOUND"),
        ("monitor", "", "NO_TEMPLATE"),
    ],
)
def test_template_selection_errors(
    client: TestClient, db: Session, asset_type: str, template_name: str | None, code: str
) -> None:
    asset = first_in_stock(db, asset_type)
    body: dict[str, object] = {}
    if template_name is None:
        body["template_id"] = 999999
    elif template_name:
        body["template_id"] = template_id(db, template_name)
    response = start(client, db, asset, **body)
    assert response.status_code == 400
    assert error_code(response) == code
    assert asset_by_tag(db, asset.asset_tag).status == "in_stock"


def test_kitting_cannot_be_started_twice(client: TestClient, db: Session) -> None:
    """No duplicate active kitting: a second start does not create a parallel checklist."""
    busy = asset_by_tag(db, "PC-0016")
    response = start(client, db, busy)
    assert error_code(response) == "KITTING_ALREADY_ACTIVE"
    assert (
        db.scalar(
            select(func.count()).select_from(KittingTask).where(KittingTask.asset_id == busy.id)
        )
        == 7
    )


@pytest.mark.parametrize("status", ["ready", "assigned", "retired", "ordered"])
def test_kitting_starts_only_from_in_stock(client: TestClient, db: Session, status: str) -> None:
    asset = db.scalars(
        select(Asset).where(Asset.status == status, Asset.type == "laptop").order_by(Asset.id)
    ).first()
    response = start(client, db, asset)
    assert error_code(response) == "INVALID_STATUS_CHANGE"
    assert (
        db.scalar(
            select(func.count()).select_from(KittingTask).where(KittingTask.asset_id == asset.id)
        )
        == 0
    )


def test_status_endpoint_cannot_start_kitting(client: TestClient, db: Session) -> None:
    laptop = first_in_stock(db, "laptop")
    response = client.post(
        f"/api/assets/{laptop.id}/status",
        json={"new_status": "kitting"},
        headers=headers_as(db, IT),
    )
    assert error_code(response) == "KITTING_WORKFLOW_REQUIRED"


@pytest.mark.parametrize("email", [MANAGER, EMPLOYEE])
def test_only_it_staff_can_start_or_tick(client: TestClient, db: Session, email: str) -> None:
    headers = headers_as(db, email)
    laptop = first_in_stock(db, "laptop")
    assert (
        client.post(f"/api/assets/{laptop.id}/kitting/start", json={}, headers=headers).status_code
        == 403
    )
    task = db.scalars(select(KittingTask).where(KittingTask.done.is_(False))).first()
    assert (
        client.patch(
            f"/api/kitting-tasks/{task.id}", json={"done": True}, headers=headers
        ).status_code
        == 403
    )


def test_failed_start_rolls_back_everything(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    laptop = first_in_stock(db, "laptop")
    original = audit_service.record

    def fail_on_kitting_started(*args: object, **kwargs: object) -> object:
        if args[2] == "KITTING_STARTED":
            raise RuntimeError("audit storage failed")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(audit_service, "record", fail_on_kitting_started)
    assert start(client, db, laptop).status_code == 500
    assert asset_by_tag(db, laptop.asset_tag).status == "in_stock"
    assert (
        db.scalar(
            select(func.count()).select_from(KittingTask).where(KittingTask.asset_id == laptop.id)
        )
        == 0
    )


# Ticking steps


def test_tick_and_untick_a_step(client: TestClient, db: Session) -> None:
    busy = asset_by_tag(db, "PC-0016")
    open_task = next(t for t in checklist(client, db, busy)["tasks"] if not t["done"])

    ticked = tick(client, db, open_task["id"]).json()
    assert ticked["done"] is True and ticked["done_at"] is not None
    assert ticked["done_by"] == db.scalar(
        select(AuditLog.user_id).where(AuditLog.action == "KITTING_STEP_DONE")
    )
    assert checklist(client, db, busy)["done"] == 4

    unticked = tick(client, db, open_task["id"], done=False).json()
    assert (unticked["done"], unticked["done_by"], unticked["done_at"]) == (False, None, None)
    assert audit_actions(db, busy.id)[-2:] == ["KITTING_STEP_DONE", "KITTING_STEP_UNDONE"]


def test_repeated_tick_changes_nothing(client: TestClient, db: Session) -> None:
    busy = asset_by_tag(db, "PC-0016")
    done_task = next(t for t in checklist(client, db, busy)["tasks"] if t["done"])
    response = tick(client, db, done_task["id"])
    assert response.status_code == 200
    assert response.json()["done_at"] == done_task["done_at"]
    assert audit_actions(db, busy.id) == []


def test_steps_of_an_old_run_are_read_only(client: TestClient, db: Session) -> None:
    tablet = asset_by_tag(db, "TB-0051")
    old_run = checklist(client, db, tablet, "?run_no=1")
    assert old_run["editable"] is False and old_run["percent"] == 100
    response = tick(client, db, old_run["tasks"][0]["id"], done=False)
    assert error_code(response) == "KITTING_NOT_ACTIVE"


def test_unknown_task_is_404(client: TestClient, db: Session) -> None:
    assert tick(client, db, 999999).status_code == 404


def test_kitting_then_ready_end_to_end(client: TestClient, db: Session) -> None:
    """Finish every step, then kitting -> ready is allowed and steps become read-only."""
    busy = asset_by_tag(db, "PC-0017")  # 6 of 7 done
    headers = headers_as(db, IT)
    status_url = f"/api/assets/{busy.id}/status"
    blocked = client.post(status_url, json={"new_status": "ready"}, headers=headers)
    assert error_code(blocked) == "KITTING_NOT_COMPLETE"

    last = next(t for t in checklist(client, db, busy)["tasks"] if not t["done"])
    tick(client, db, last["id"])
    assert checklist(client, db, busy)["percent"] == 100
    ready = client.post(status_url, json={"new_status": "ready"}, headers=headers)
    assert ready.json()["status"] == "ready"

    after = checklist(client, db, busy)
    assert after["editable"] is False
    assert error_code(tick(client, db, last["id"], done=False)) == "KITTING_NOT_ACTIVE"


def test_rekit_starts_a_new_run_and_keeps_the_old_one(client: TestClient, db: Session) -> None:
    """Approved decision: wiped -> in_stock -> kitting again adds run 2 next to run 1."""
    headers = headers_as(db, IT)
    wiped = db.scalars(select(Asset).where(Asset.status == "wiped", Asset.type == "laptop")).first()
    db.add(
        KittingTask(
            asset_id=wiped.id,
            run_no=1,
            step_no=1,
            step_en="Old",
            step_ja="旧",
            done=True,
            done_at=func.now(),
        )
    )
    db.commit()
    client.post(f"/api/assets/{wiped.id}/status", json={"new_status": "in_stock"}, headers=headers)

    body = start(client, db, wiped).json()
    assert (body["run_no"], body["runs"], body["total"]) == (2, [1, 2], 7)
    old = checklist(client, db, wiped, "?run_no=1")
    assert [t["step_en"] for t in old["tasks"]] == ["Old"]
    assert old["editable"] is False


# Reading checklists


def test_never_kitted_device_has_an_empty_checklist(client: TestClient, db: Session) -> None:
    monitor = db.scalars(select(Asset).where(Asset.type == "monitor")).first()
    body = checklist(client, db, monitor)
    assert (body["run_no"], body["runs"], body["tasks"], body["percent"]) == (None, [], [], 0)


def test_unknown_run_is_404(client: TestClient, db: Session) -> None:
    busy = asset_by_tag(db, "PC-0016")
    response = client.get(f"/api/assets/{busy.id}/kitting?run_no=9", headers=headers_as(db, IT))
    assert error_code(response) == "KITTING_RUN_NOT_FOUND"


def test_checklist_access_follows_asset_scope(client: TestClient, db: Session) -> None:
    """Devices in kitting are not held by anyone, so managers do not see them (Part B.2)."""
    busy = asset_by_tag(db, "PC-0016")
    url = f"/api/assets/{busy.id}/kitting"
    assert client.get(url, headers=headers_as(db, MANAGER)).status_code == 404
    assert client.get(url, headers=headers_as(db, EMPLOYEE)).status_code == 403


# Board


def test_board_groups_devices_by_worker(client: TestClient, db: Session) -> None:
    response = client.get("/api/kitting/board", headers=headers_as(db, IT))
    assert response.status_code == 200
    groups = {g["worker"]["email"]: g["devices"] for g in response.json()}
    assert list(groups) == ["admin@demo", "it@demo"]
    progress = {d["asset_tag"]: d["percent"] for devices in groups.values() for d in devices}
    assert progress == {"PC-0016": 43, "PC-0017": 86, "SP-0039": 33, "TB-0051": 17}
    assert {d["asset_tag"] for d in groups["it@demo"]} == {"PC-0016", "SP-0039"}


def test_board_uses_the_starter_until_someone_ticks(client: TestClient, db: Session) -> None:
    laptop = first_in_stock(db, "laptop")
    client.post(
        f"/api/assets/{laptop.id}/kitting/start", json={}, headers=headers_as(db, "admin@demo")
    )
    groups = client.get("/api/kitting/board", headers=headers_as(db, IT)).json()
    admin_group = next(g for g in groups if g["worker"]["email"] == "admin@demo")
    assert laptop.asset_tag in {d["asset_tag"] for d in admin_group["devices"]}


def test_board_lists_unassigned_devices_last(client: TestClient, db: Session) -> None:
    orphan = first_in_stock(db, "laptop")
    orphan.status = "kitting"
    db.add(KittingTask(asset_id=orphan.id, run_no=1, step_no=1, step_en="S", step_ja="手順"))
    db.commit()
    groups = client.get("/api/kitting/board", headers=headers_as(db, IT)).json()
    assert groups[-1]["worker"] is None
    assert [d["asset_tag"] for d in groups[-1]["devices"]] == [orphan.asset_tag]


@pytest.mark.parametrize("email", [MANAGER, EMPLOYEE])
def test_board_is_it_only(client: TestClient, db: Session, email: str) -> None:
    assert client.get("/api/kitting/board", headers=headers_as(db, email)).status_code == 403
