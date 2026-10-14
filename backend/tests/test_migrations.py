"""Phase 2 tests: Alembic migrations against an empty PostgreSQL database."""

import os

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
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
