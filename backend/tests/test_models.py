"""Phase 2 tests: database constraints that protect the business rules.

Each test runs inside a rolled-back transaction (db_session fixture).
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    ChatSession,
    DeviceLoan,
    Employee,
    KittingTask,
    Ticket,
    User,
)

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def make_employee(session: Session, code: str = "T0001") -> Employee:
    employee = Employee(
        employee_code=code,
        name="テスト 太郎",
        email=f"{code.lower()}@example.co.jp",
        department="情報システム部",
        position="一般",
        join_date=date(2024, 4, 1),
    )
    session.add(employee)
    session.flush()
    return employee


def make_user(session: Session, email: str = "it@test", employee: Employee | None = None) -> User:
    user = User(email=email, password_hash="x" * 60, role="it_admin", employee=employee)
    session.add(user)
    session.flush()
    return user


def make_asset(session: Session, tag: str = "PC-T001", **fields: object) -> Asset:
    values: dict[str, object] = {
        "asset_tag": tag,
        "type": "laptop",
        "serial_number": f"SN-{tag}",
        "manufacturer": "Dell",
        "model": "Latitude 5440",
        "status": "in_stock",
    }
    values.update(fields)
    asset = Asset(**values)
    session.add(asset)
    session.flush()
    return asset


def assert_rejected(session: Session, action: Callable[[], object]) -> None:
    """Run an action inside a savepoint and expect the database to reject it."""
    with pytest.raises(IntegrityError), session.begin_nested():
        action()
        session.flush()


# Asset holder consistency


def test_assigned_asset_requires_a_holder(db_session: Session) -> None:
    assert_rejected(db_session, lambda: make_asset(db_session, status="assigned"))


def test_unheld_asset_cannot_have_a_holder(db_session: Session) -> None:
    employee = make_employee(db_session)
    assert_rejected(
        db_session,
        lambda: make_asset(db_session, status="in_stock", assigned_to=employee.id),
    )


def test_held_statuses_accept_a_holder(db_session: Session) -> None:
    employee = make_employee(db_session)
    make_asset(db_session, "PC-T001", status="assigned", assigned_to=employee.id)
    make_asset(db_session, "PC-T002", status="on_loan", assigned_to=employee.id)
    make_asset(db_session, "PC-T003", status="repair", assigned_to=employee.id)


def test_repair_keeps_the_holder(db_session: Session) -> None:
    """Approved decision: a device in repair still belongs to its holder."""
    assert_rejected(db_session, lambda: make_asset(db_session, status="repair"))


@pytest.mark.parametrize("status", ["ready", "returned", "wiped", "retired"])
def test_holder_must_be_cleared_outside_held_statuses(db_session: Session, status: str) -> None:
    employee = make_employee(db_session)
    assert_rejected(
        db_session, lambda: make_asset(db_session, status=status, assigned_to=employee.id)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", "lost"), ("type", "server"), ("cost", -1)],
)
def test_asset_rejects_invalid_values(db_session: Session, field: str, value: object) -> None:
    assert_rejected(db_session, lambda: make_asset(db_session, **{field: value}))


def test_asset_tag_and_serial_number_are_unique(db_session: Session) -> None:
    make_asset(db_session, "PC-T001")
    assert_rejected(db_session, lambda: make_asset(db_session, "PC-T001", serial_number="OTHER"))
    assert_rejected(
        db_session, lambda: make_asset(db_session, "PC-T999", serial_number="SN-PC-T001")
    )


# Loans


def make_loan(session: Session, asset: Asset, employee: Employee, user: User) -> DeviceLoan:
    loan = DeviceLoan(
        asset_id=asset.id,
        employee_id=employee.id,
        lent_by=user.id,
        lent_at=NOW,
        due_at=NOW + timedelta(days=7),
    )
    session.add(loan)
    session.flush()
    return loan


def test_only_one_open_loan_per_device(db_session: Session) -> None:
    employee = make_employee(db_session)
    user = make_user(db_session)
    asset = make_asset(db_session, status="on_loan", assigned_to=employee.id)
    first = make_loan(db_session, asset, employee, user)

    assert_rejected(db_session, lambda: make_loan(db_session, asset, employee, user))

    # After the first loan is returned, the device can be lent again.
    first.returned_at = NOW + timedelta(days=1)
    first.condition = "ok"
    db_session.flush()
    make_loan(db_session, asset, employee, user)


def test_returned_loan_requires_a_condition(db_session: Session) -> None:
    employee = make_employee(db_session)
    user = make_user(db_session)
    asset = make_asset(db_session)
    loan = make_loan(db_session, asset, employee, user)

    def return_without_condition() -> None:
        loan.returned_at = NOW + timedelta(days=1)

    assert_rejected(db_session, return_without_condition)


def test_loan_due_date_must_be_after_lend_date(db_session: Session) -> None:
    employee = make_employee(db_session)
    user = make_user(db_session)
    asset = make_asset(db_session)

    def backwards_loan() -> None:
        db_session.add(
            DeviceLoan(
                asset_id=asset.id,
                employee_id=employee.id,
                lent_by=user.id,
                lent_at=NOW,
                due_at=NOW - timedelta(days=1),
            )
        )

    assert_rejected(db_session, backwards_loan)


# Users and employees


def test_user_role_must_be_known(db_session: Session) -> None:
    def bad_role() -> None:
        db_session.add(User(email="x@test", password_hash="x" * 60, role="root"))

    assert_rejected(db_session, bad_role)


def test_an_employee_can_have_only_one_login(db_session: Session) -> None:
    employee = make_employee(db_session)
    make_user(db_session, "first@test", employee)
    assert_rejected(db_session, lambda: make_user(db_session, "second@test", employee))


def test_employee_with_history_cannot_be_hard_deleted(db_session: Session) -> None:
    """Leavers get status "left"; a hard delete must fail while history points at them."""
    employee = make_employee(db_session)
    db_session.add(
        Ticket(title="PC slow", description="...", category="laptop", requester_id=employee.id)
    )
    db_session.flush()
    assert_rejected(
        db_session,
        lambda: db_session.execute(delete(Employee).where(Employee.id == employee.id)),
    )


def test_user_defaults(db_session: Session) -> None:
    user = make_user(db_session)
    db_session.refresh(user)
    assert user.language == "ja"
    assert user.is_active is True
    assert user.created_at.tzinfo is not None


def test_updated_at_changes_on_update(test_engine: Engine) -> None:
    """now() is fixed for a whole transaction, so this needs two real commits."""
    with Session(test_engine) as session:
        employee = make_employee(session, "T9999")
        session.commit()
        created = employee.created_at
        try:
            employee.position = "主任"
            session.commit()
            session.refresh(employee)
            assert employee.updated_at > created
            assert employee.created_at == created
        finally:
            session.delete(employee)
            session.commit()


# Kitting and chat


def test_completed_kitting_step_must_record_when(db_session: Session) -> None:
    asset = make_asset(db_session, status="kitting")

    def done_without_time() -> None:
        db_session.add(
            KittingTask(asset_id=asset.id, step_no=1, step_en="Step", step_ja="手順", done=True)
        )

    assert_rejected(db_session, done_without_time)


def test_pending_chat_action_requires_an_expiry(db_session: Session) -> None:
    user = make_user(db_session)

    def pending_without_expiry() -> None:
        db_session.add(ChatSession(user_id=user.id, pending_action={"tool": "create_ticket"}))

    assert_rejected(db_session, pending_without_expiry)

    db_session.add(
        ChatSession(
            user_id=user.id,
            pending_action={"tool": "create_ticket"},
            pending_expires_at=NOW + timedelta(minutes=10),
        )
    )
    db_session.flush()


def add_task(session: Session, asset: Asset, run_no: int, step_no: int) -> None:
    session.add(
        KittingTask(asset_id=asset.id, run_no=run_no, step_no=step_no, step_en="S", step_ja="手順")
    )
    session.flush()


def test_kitting_step_is_unique_within_a_run(db_session: Session) -> None:
    asset = make_asset(db_session, status="kitting")
    add_task(db_session, asset, 1, 1)
    assert_rejected(db_session, lambda: add_task(db_session, asset, 1, 1))


def test_rekit_keeps_earlier_runs(db_session: Session) -> None:
    """Approved decision: a re-kit adds run 2 next to run 1 instead of replacing it."""
    asset = make_asset(db_session, status="kitting")
    add_task(db_session, asset, 1, 1)
    add_task(db_session, asset, 2, 1)
    runs = db_session.scalars(select(KittingTask.run_no).where(KittingTask.asset_id == asset.id))
    assert sorted(runs) == [1, 2]


def test_kitting_run_defaults_to_one(db_session: Session) -> None:
    asset = make_asset(db_session, status="kitting")
    task = KittingTask(asset_id=asset.id, step_no=1, step_en="S", step_ja="手順")
    db_session.add(task)
    db_session.flush()
    db_session.refresh(task)
    assert task.run_no == 1
