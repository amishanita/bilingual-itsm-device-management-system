"""Keep the holder during repair, and number kitting runs to keep re-kit history.

Two approved design decisions:
- A device in repair keeps assigned_to. The holder check now covers repair too.
- kitting_tasks gets run_no. A re-kit starts a new run, so older checklists
  stay in the table as history. Existing rows become run 1.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.f() marks names as final so the naming convention is not applied twice.
HOLDER_CHECK = op.f("ck_assets_assigned_to_matches_status")
RUN_CHECK = op.f("ck_kitting_tasks_run_no_positive")
RUN_UNIQUE = op.f("uq_kitting_tasks_asset_run_step")


def upgrade() -> None:
    """Widen the holder check to include repair and add kitting run numbers."""
    op.drop_constraint(HOLDER_CHECK, "assets", type_="check")
    op.create_check_constraint(
        HOLDER_CHECK,
        "assets",
        "(status IN ('assigned', 'on_loan', 'repair')) = (assigned_to IS NOT NULL)",
    )

    op.add_column(
        "kitting_tasks",
        sa.Column("run_no", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(RUN_CHECK, "kitting_tasks", "run_no >= 1")
    op.create_unique_constraint(RUN_UNIQUE, "kitting_tasks", ["asset_id", "run_no", "step_no"])


def downgrade() -> None:
    """Restore the 0001 rules.

    The old holder check forbids a holder on repair devices, so those holders
    are cleared first. This loses who held each device under repair, which is
    unavoidable when going back to the older rule.
    """
    op.drop_constraint(RUN_UNIQUE, "kitting_tasks", type_="unique")
    op.drop_constraint(RUN_CHECK, "kitting_tasks", type_="check")
    op.drop_column("kitting_tasks", "run_no")

    op.drop_constraint(HOLDER_CHECK, "assets", type_="check")
    op.execute("UPDATE assets SET assigned_to = NULL WHERE status = 'repair'")
    op.create_check_constraint(
        HOLDER_CHECK,
        "assets",
        "(status IN ('assigned', 'on_loan')) = (assigned_to IS NOT NULL)",
    )
