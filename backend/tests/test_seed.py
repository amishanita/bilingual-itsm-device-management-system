"""Phase 2 tests: seed safety, repeatability, and rollback.

These tests commit for real (the seed controls its own transaction), so they
only ever run against the validated _test database.
"""

import os
from collections import Counter
from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import seed
from app.core.config import AppEnv, Settings
from app.core.security import verify_password
from app.models import AuditLog, Employee, User

DEMO_PASSWORD = "demo-pass-1234"


def settings_for(app_env: AppEnv, password: str | None = DEMO_PASSWORD) -> Settings:
    return Settings(
        _env_file=None,
        app_env=app_env,
        database_url=os.environ["TEST_DATABASE_URL"],
        jwt_secret=SecretStr(os.environ["JWT_SECRET"]),
        demo_password=SecretStr(password) if password is not None else None,
    )


@pytest.fixture
def session(test_engine: Engine) -> Iterator[Session]:
    with Session(test_engine) as db:
        yield db


def counts(session: Session) -> tuple[int, int]:
    users = session.scalar(select(func.count()).select_from(User))
    employees = session.scalar(select(func.count()).select_from(Employee))
    return users, employees


def test_seed_refuses_to_run_in_production(session: Session) -> None:
    seed.run_seed(session, settings_for(AppEnv.DEVELOPMENT))
    with pytest.raises(seed.SeedRefusedError, match="production"):
        seed.run_seed(session, settings_for(AppEnv.PRODUCTION))
    # Nothing was touched.
    assert counts(session) == (4, 30)


@pytest.mark.parametrize("password", [None, "", "short", "x" * 73, "あ" * 25])
def test_seed_refuses_missing_or_invalid_password(session: Session, password: str | None) -> None:
    with pytest.raises(seed.SeedRefusedError):
        seed.run_seed(session, settings_for(AppEnv.DEMO, password))


def test_seed_creates_expected_users_and_employees(session: Session) -> None:
    result = seed.run_seed(session, settings_for(AppEnv.DEMO))
    assert result == {"employees": 30, "users": 4, "assets": 60, "kitting_devices": 4}
    assert counts(session) == (4, 30)

    departments = Counter(session.scalars(select(Employee.department)))
    assert departments == dict.fromkeys(seed.DEPARTMENTS, 6)

    users = {u.email: u for u in session.scalars(select(User))}
    assert {email: u.role for email, u in users.items()} == {
        "admin@demo": "super_admin",
        "it@demo": "it_admin",
        "manager@demo": "manager",
        "employee@demo": "employee",
    }
    for user in users.values():
        assert user.employee is not None
        assert user.employee.status == "active"
        assert user.is_active and user.language == "ja"
        assert verify_password(DEMO_PASSWORD, user.password_hash)
        assert not verify_password("wrong-password", user.password_hash)

    # Manager and employee share a department so isolation can be tested later.
    assert users["manager@demo"].employee.department == users["employee@demo"].employee.department


def test_seed_is_repeatable_with_same_counts_and_ids(session: Session) -> None:
    seed.run_seed(session, settings_for(AppEnv.DEVELOPMENT))
    first = sorted(session.execute(select(User.id, User.email, User.employee_id)).all())
    first_employees = sorted(session.execute(select(Employee.id, Employee.employee_code)).all())

    seed.run_seed(session, settings_for(AppEnv.DEVELOPMENT))
    second = sorted(session.execute(select(User.id, User.email, User.employee_id)).all())
    second_employees = sorted(session.execute(select(Employee.id, Employee.employee_code)).all())

    assert counts(session) == (4, 30)
    assert first == second
    assert first_employees == second_employees
    # Old audit rows were replaced, not stacked up.
    assert session.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_seed_audit_entry_has_no_password_data(session: Session) -> None:
    seed.run_seed(session, settings_for(AppEnv.DEMO))
    entry = session.scalars(select(AuditLog)).one()
    assert entry.action == "DEMO_DATA_SEEDED"
    assert entry.user_id is None
    text = str(entry.detail).lower()
    assert "password" not in text and DEMO_PASSWORD not in text


def test_failed_seed_rolls_back_and_keeps_previous_data(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.run_seed(session, settings_for(AppEnv.DEVELOPMENT))
    before = sorted(session.scalars(select(Employee.employee_code)))

    def broken_build_users(*_args: object) -> list[User]:
        raise RuntimeError("simulated failure after the tables were emptied")

    monkeypatch.setattr(seed, "build_users", broken_build_users)
    with pytest.raises(RuntimeError, match="simulated"):
        seed.run_seed(session, settings_for(AppEnv.DEVELOPMENT))

    # TRUNCATE ran inside the same transaction, so the rollback restored everything.
    assert counts(session) == (4, 30)
    assert sorted(session.scalars(select(Employee.employee_code))) == before


def test_seed_command_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """python -m app.seed returns 2 and does nothing when refused."""
    monkeypatch.setattr(seed, "get_settings", lambda: settings_for(AppEnv.PRODUCTION))
    assert seed.main() == 2


def test_seed_command_reports_missing_settings_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_secret() -> Settings:
        return Settings(_env_file=None, database_url="postgresql+psycopg://x@y/z")

    monkeypatch.setattr(seed, "get_settings", missing_secret)
    assert seed.main() == 2
