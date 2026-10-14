"""Phase 2 tests: Alembic migrations against an empty PostgreSQL database."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import Base
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "users",
    "employees",
    "assets",
    "device_details",
    "kitting_templates",
    "kitting_tasks",
    "device_loans",
    "tickets",
    "ticket_comments",
    "faq_articles",
    "chat_sessions",
    "chat_messages",
    "audit_logs",
}


def test_upgrade_creates_every_table(test_engine: Engine) -> None:
    tables = set(inspect(test_engine).get_table_names())
    assert tables == EXPECTED_TABLES | {"alembic_version"}


def test_migration_matches_the_models_exactly(test_engine: Engine) -> None:
    """If a model changes without a new migration, this lists the difference."""
    with test_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_every_table_has_utc_aware_timestamps(test_engine: Engine) -> None:
    inspector = inspect(test_engine)
    for table in EXPECTED_TABLES:
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        for name in ("created_at", "updated_at"):
            assert name in columns, f"{table}.{name} is missing"
            assert columns[name]["type"].timezone is True, f"{table}.{name} is not timezone-aware"
            assert columns[name]["nullable"] is False


def test_downgrade_to_empty_and_upgrade_again(test_engine: Engine) -> None:
    config = alembic_config(os.environ["TEST_DATABASE_URL"])

    command.downgrade(config, "base")
    assert set(inspect(test_engine).get_table_names()) == {"alembic_version"}

    command.upgrade(config, "head")
    assert set(inspect(test_engine).get_table_names()) == EXPECTED_TABLES | {"alembic_version"}


def constraint_definition(engine: Engine, name: str) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        )


def test_hand_written_constraints_have_the_expected_names(test_engine: Engine) -> None:
    """compare_metadata ignores CHECK constraints, so verify them directly."""
    holder = constraint_definition(test_engine, "ck_assets_assigned_to_matches_status")
    assert holder is not None and "repair" in holder
    assert constraint_definition(test_engine, "ck_kitting_tasks_run_no_positive") is not None
    assert constraint_definition(test_engine, "uq_kitting_tasks_asset_run_step") is not None


def test_0002_keeps_existing_data_and_downgrades_cleanly(test_engine: Engine) -> None:
    """Upgrade 0001 -> 0002 with real rows in place, then go back down."""
    config = alembic_config(os.environ["TEST_DATABASE_URL"])
    command.downgrade(config, "base")
    command.upgrade(config, "0001")
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO employees"
                " (employee_code, name, email, department, position, join_date)"
                " VALUES ('M0001', 'テスト', 'm@example.co.jp', '総務部', '一般', '2024-04-01')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO assets (asset_tag, type, serial_number, manufacturer, model, status)"
                " VALUES ('PC-M001', 'laptop', 'SN-M001', 'Dell', 'Latitude', 'kitting')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO kitting_tasks (asset_id, step_no, step_en, step_ja)"
                " SELECT id, 1, 'Step', '手順' FROM assets WHERE asset_tag = 'PC-M001'"
            )
        )

    command.upgrade(config, "0002")
    with test_engine.begin() as connection:
        assert connection.scalar(text("SELECT run_no FROM kitting_tasks")) == 1
        # Under 0002 a repair device keeps its holder.
        connection.execute(
            text(
                "UPDATE assets SET status = 'repair',"
                " assigned_to = (SELECT id FROM employees WHERE employee_code = 'M0001')"
            )
        )

    command.downgrade(config, "0001")
    with test_engine.connect() as connection:
        assert connection.scalar(text("SELECT assigned_to FROM assets")) is None

    command.downgrade(config, "base")
    command.upgrade(config, "head")
