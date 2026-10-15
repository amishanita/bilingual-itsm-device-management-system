"""Phase 5 tests: the device lifecycle state machine, at the service level.

Each test builds its own employee, user, and asset inside a rolled-back
transaction, so all 100 status pairs can be checked quickly and independently.
"""

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Asset, AuditLog, DeviceLoan, Employee, KittingTask, User
from app.models.base import ASSET_STATUSES, HELD_ASSET_STATUSES
from app.services import asset_service
from app.services.asset_service import TRANSITIONS, change_status

NOW = datetime.now(UTC)


def make_employee(db: Session, code: str = "L0001", status: str = "active") -> Employee:
    employee = Employee(
        employee_code=code,
        name="検証 花子",
        email=f"{code.lower()}@example.co.jp",
        department="情報システム部",
        position="一般",
        join_date=date(2024, 4, 1),
        status=status,
    )
    db.add(employee)
    db.flush()
    return employee


def make_actor(db: Session) -> User:
    user = User(email="lifecycle@test", password_hash="x" * 60, role="it_admin")
    db.add(user)
    db.flush()
    return user


def make_asset_in(db: Session, status: str, holder: Employee | None = None) -> Asset:
    """Create an asset directly in a given status, bypassing the rules (test setup only)."""
    asset = Asset(
        asset_tag=f"T-{status}",
        type="laptop",
        serial_number=f"SN-{status}",
        manufacturer="Dell",
        model="Latitude 5440",
        status=status,
        assigned_to=holder.id if status in HELD_ASSET_STATUSES and holder else None,
    )
    db.add(asset)
    db.flush()
    return asset


def add_kitting_steps(db: Session, asset: Asset, done: list[bool], run_no: int = 1) -> None:
    for step_no, is_done in enumerate(done, start=1):
        db.add(
            KittingTask(
                asset_id=asset.id,
                run_no=run_no,
                step_no=step_no,
                step_en=f"Step {step_no}",
                step_ja=f"手順 {step_no}",
                done=is_done,
                done_at=NOW if is_done else None,
            )
        )
    db.flush()


def audit_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


def expect_error(code: str, action: object) -> None:
    with pytest.raises(AppError) as error:
        action()  # type: ignore[operator]
    assert error.value.status_code == 400
    assert error.value.code == code


# Every pair of statuses


# The lifecycle exactly as the specification states it. Written out here
# independently, so a mistake in the service's own table cannot also hide
# in the answer key.
SPEC_FORWARD = {
    "ordered": {"in_stock"},
    "in_stock": {"kitting"},
    "kitting": {"ready"},
    "ready": {"assigned", "on_loan"},
    "assigned": {"returned", "repair"},
    "on_loan": {"returned"},
    "returned": {"wiped"},
    "wiped": {"in_stock"},
    "repair": {"ready"},
    "retired": set(),
}
SPEC = {
    status: targets if status == "retired" else targets | {"retired"}
    for status, targets in SPEC_FORWARD.items()
}

ALL_PAIRS = [(a, b) for a in ASSET_STATUSES for b in ASSET_STATUSES]


@pytest.mark.parametrize(
    ("current", "requested"), ALL_PAIRS, ids=[f"{a}->{b}" for a, b in ALL_PAIRS]
)
def test_every_status_pair(db_session: Session, current: str, requested: str) -> None:
    """Allowed moves succeed when their prerequisites are met; every other move is refused."""
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, current, holder=employee)
    if current == "kitting":
        add_kitting_steps(db_session, asset, [True, True])

    def attempt() -> Asset:
        return change_status(
            db_session,
            asset.id,
            requested,
            actor,
            employee_id=employee.id if requested in ("assigned", "on_loan") else None,
            note="Erase certificate EC-001" if requested == "retired" else None,
            wipe_confirmed=requested == "wiped",
            via_loan=True,
        )

    if requested in SPEC[current]:
        assert attempt().status == requested
    else:
        expect_error("INVALID_STATUS_CHANGE", attempt)
        db_session.refresh(asset)
        assert asset.status == current


def test_transition_table_matches_the_specification() -> None:
    assert {status: set(targets) for status, targets in TRANSITIONS.items()} == SPEC


# Prerequisites


@pytest.mark.parametrize(
    ("steps", "complete"),
    [
        ([], False),
        ([True, False, True], False),
        ([True, True, True], True),
    ],
    ids=["no-steps", "one-open", "all-done"],
)
def test_kitting_must_be_complete_before_ready(
    db_session: Session, steps: list[bool], complete: bool
) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "kitting")
    add_kitting_steps(db_session, asset, steps)
    if complete:
        assert change_status(db_session, asset.id, "ready", actor).status == "ready"
    else:
        expect_error(
            "KITTING_NOT_COMPLETE", lambda: change_status(db_session, asset.id, "ready", actor)
        )


def test_only_the_latest_kitting_run_counts(db_session: Session) -> None:
    """An unfinished old run does not block; an unfinished new run does."""
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "kitting")
    add_kitting_steps(db_session, asset, [True, False], run_no=1)
    add_kitting_steps(db_session, asset, [True, True], run_no=2)
    assert change_status(db_session, asset.id, "ready", actor).status == "ready"

    other = Asset(
        asset_tag="T-k2",
        type="laptop",
        serial_number="SN-k2",
        manufacturer="X",
        model="Y",
        status="kitting",
    )
    db_session.add(other)
    db_session.flush()
    add_kitting_steps(db_session, other, [True, True], run_no=1)
    add_kitting_steps(db_session, other, [True, False], run_no=2)
    expect_error(
        "KITTING_NOT_COMPLETE", lambda: change_status(db_session, other.id, "ready", actor)
    )


@pytest.mark.parametrize("target", ["assigned", "on_loan"])
def test_handover_needs_an_employee(db_session: Session, target: str) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "ready")
    expect_error(
        "EMPLOYEE_REQUIRED",
        lambda: change_status(db_session, asset.id, target, actor, via_loan=True),
    )
    expect_error(
        "EMPLOYEE_NOT_FOUND",
        lambda: change_status(
            db_session, asset.id, target, actor, employee_id=999999, via_loan=True
        ),
    )


@pytest.mark.parametrize("status", ["on_leave", "left"])
def test_handover_needs_an_active_employee(db_session: Session, status: str) -> None:
    actor = make_actor(db_session)
    inactive = make_employee(db_session, status=status)
    asset = make_asset_in(db_session, "ready")
    expect_error(
        "EMPLOYEE_NOT_ACTIVE",
        lambda: change_status(db_session, asset.id, "assigned", actor, employee_id=inactive.id),
    )
    db_session.refresh(asset)
    assert (asset.status, asset.assigned_to) == ("ready", None)


def test_wipe_needs_confirmation(db_session: Session) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "returned")
    expect_error(
        "WIPE_CONFIRMATION_REQUIRED", lambda: change_status(db_session, asset.id, "wiped", actor)
    )
    assert (
        change_status(db_session, asset.id, "wiped", actor, wipe_confirmed=True).status == "wiped"
    )


@pytest.mark.parametrize("note", [None, ""])
def test_retirement_needs_a_note(db_session: Session, note: str | None) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "in_stock")
    expect_error(
        "RETIREMENT_NOTE_REQUIRED",
        lambda: change_status(db_session, asset.id, "retired", actor, note=note),
    )


def test_retirement_records_the_note(db_session: Session) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "in_stock")
    asset.notes = "Old keyboard"
    change_status(db_session, asset.id, "retired", actor, note="Erase certificate EC-778")
    assert asset.notes.startswith("Old keyboard\n[")
    assert asset.notes.endswith("retired] Erase certificate EC-778")


def test_device_on_open_loan_cannot_be_retired(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "on_loan", holder=employee)
    db_session.add(
        DeviceLoan(
            asset_id=asset.id,
            employee_id=employee.id,
            lent_by=actor.id,
            lent_at=NOW - timedelta(days=2),
            due_at=NOW + timedelta(days=5),
        )
    )
    db_session.flush()
    expect_error(
        "OPEN_LOAN_EXISTS",
        lambda: change_status(db_session, asset.id, "retired", actor, note="Lost"),
    )


@pytest.mark.parametrize(("current", "requested"), [("ready", "on_loan"), ("on_loan", "returned")])
def test_loan_moves_require_the_loan_workflow(
    db_session: Session, current: str, requested: str
) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, current, holder=employee)
    expect_error(
        "LOAN_WORKFLOW_REQUIRED",
        lambda: change_status(db_session, asset.id, requested, actor, employee_id=employee.id),
    )


def test_employee_is_refused_where_it_has_no_meaning(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "ordered")
    expect_error(
        "EMPLOYEE_NOT_ALLOWED",
        lambda: change_status(db_session, asset.id, "in_stock", actor, employee_id=employee.id),
    )


def test_unknown_asset_is_404(db_session: Session) -> None:
    actor = make_actor(db_session)
    with pytest.raises(AppError) as error:
        change_status(db_session, 999999, "in_stock", actor)
    assert error.value.status_code == 404


# Holder rules


def test_holder_follows_the_lifecycle(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "ready")

    change_status(db_session, asset.id, "assigned", actor, employee_id=employee.id)
    assert asset.assigned_to == employee.id
    change_status(db_session, asset.id, "repair", actor)
    assert asset.assigned_to == employee.id, "repair keeps the holder (approved decision)"
    change_status(db_session, asset.id, "ready", actor)
    assert asset.assigned_to is None, "repair -> ready clears the holder"
    change_status(db_session, asset.id, "assigned", actor, employee_id=employee.id)
    change_status(db_session, asset.id, "returned", actor)
    assert asset.assigned_to is None


def test_retiring_a_held_device_clears_the_holder(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "assigned", holder=employee)
    change_status(db_session, asset.id, "retired", actor, note="Broken beyond repair")
    assert asset.assigned_to is None


def test_retired_is_final(db_session: Session) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "retired")
    assert asset_service.allowed_transitions(asset) == []
    for status in ASSET_STATUSES:
        expect_error(
            "INVALID_STATUS_CHANGE",
            lambda status=status: change_status(
                db_session, asset.id, status, actor, note="x", wipe_confirmed=True, via_loan=True
            ),
        )


# Audit


def test_assignment_is_audited_with_old_and_new_status(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "ready")
    change_status(db_session, asset.id, "assigned", actor, employee_id=employee.id, note="New hire")
    entry = db_session.scalars(select(AuditLog).where(AuditLog.entity_id == asset.id)).one()
    assert (entry.action, entry.entity, entry.user_id) == ("ASSET_ASSIGNED", "asset", actor.id)
    assert entry.detail == {
        "old_status": "ready",
        "new_status": "assigned",
        "employee_id": employee.id,
        "note": "New hire",
    }


def test_status_change_and_return_are_audited(db_session: Session) -> None:
    employee = make_employee(db_session)
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "assigned", holder=employee)
    change_status(db_session, asset.id, "returned", actor)
    entry = db_session.scalars(select(AuditLog).where(AuditLog.entity_id == asset.id)).one()
    assert entry.action == "ASSET_STATUS_CHANGED"
    assert entry.detail == {
        "old_status": "assigned",
        "new_status": "returned",
        "previous_employee_id": employee.id,
    }


def test_wipe_is_audited_as_an_operator_confirmation(db_session: Session) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "returned")
    change_status(db_session, asset.id, "wiped", actor, wipe_confirmed=True)
    entry = db_session.scalars(select(AuditLog).where(AuditLog.entity_id == asset.id)).one()
    assert entry.detail["wipe_confirmed"] is True


def test_refused_change_writes_no_audit_row(db_session: Session) -> None:
    actor = make_actor(db_session)
    asset = make_asset_in(db_session, "ordered")
    before = audit_count(db_session)
    expect_error(
        "INVALID_STATUS_CHANGE", lambda: change_status(db_session, asset.id, "assigned", actor)
    )
    assert audit_count(db_session) == before


# Concurrency


def seeded_ready_asset(db: Session) -> Asset:
    return db.scalars(select(Asset).where(Asset.status == "ready").order_by(Asset.id)).first()


def test_status_change_waits_for_the_row_lock(test_engine: Engine, db: Session) -> None:
    """A second writer cannot change an asset while another transaction holds its lock."""
    asset_id = seeded_ready_asset(db).id
    actor_id = db.scalar(select(User.id).where(User.email == "it@demo"))
    employee_id = db.scalar(select(Employee.id).where(Employee.employee_code == "E0003"))

    with Session(test_engine) as holder, Session(test_engine) as challenger:
        asset_service.lock_asset(holder, asset_id)
        challenger.execute(text("SET LOCAL lock_timeout = '300ms'"))
        actor = challenger.get(User, actor_id)
        with pytest.raises(OperationalError, match="lock"):
            change_status(challenger, asset_id, "assigned", actor, employee_id=employee_id)
        challenger.rollback()
        holder.rollback()


def test_simultaneous_assignments_give_one_winner(test_engine: Engine, db: Session) -> None:
    """Two IT staff assign the same ready device to different people at the same moment."""
    asset_id = seeded_ready_asset(db).id
    actor_id = db.scalar(select(User.id).where(User.email == "it@demo"))
    candidates = [
        db.scalar(select(Employee.id).where(Employee.employee_code == code))
        for code in ("E0003", "E0004")
    ]
    barrier = threading.Barrier(2)
    results: list[str] = []

    def assign(employee_id: int) -> None:
        with Session(test_engine) as session:
            actor = session.get(User, actor_id)
            barrier.wait()
            try:
                change_status(session, asset_id, "assigned", actor, employee_id=employee_id)
                session.commit()
                results.append("ok")
            except AppError as exc:
                session.rollback()
                results.append(exc.code)

    threads = [threading.Thread(target=assign, args=(e,)) for e in candidates]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(results) == ["INVALID_STATUS_CHANGE", "ok"]
    db.expire_all()
    final = db.get(Asset, asset_id)
    assert final.status == "assigned" and final.assigned_to in candidates
    assigned_rows = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity_id == asset_id, AuditLog.action == "ASSET_ASSIGNED")
    )
    assert assigned_rows == 1
