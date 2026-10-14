"""Initial schema: every table, constraint, and index of the data model.

Revision ID: 0001
Revises:
Create Date: 2026-10-15 00:46:44.023842
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables. Tables are created in foreign-key order."""
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=False),
        sa.Column("position", sa.String(length=100), nullable=False),
        sa.Column("join_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'on_leave', 'left')", name=op.f("ck_employees_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("email", name=op.f("uq_employees_email")),
        sa.UniqueConstraint("employee_code", name=op.f("uq_employees_employee_code")),
    )
    op.create_index("ix_employees_department", "employees", ["department"], unique=False)
    op.create_table(
        "kitting_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "device_type IN ('laptop', 'desktop', 'smartphone', 'tablet', 'monitor', 'printer')",
            name=op.f("ck_kitting_templates_device_type"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(steps) = 'array'", name=op.f("ck_kitting_templates_steps_is_array")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kitting_templates")),
    )
    op.create_index(
        "ix_kitting_templates_device_type", "kitting_templates", ["device_type"], unique=False
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_tag", sa.String(length=30), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("serial_number", sa.String(length=100), nullable=False),
        sa.Column("manufacturer", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("warranty_end", sa.Date(), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ordered", nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('assigned', 'on_loan')) = (assigned_to IS NOT NULL)",
            name=op.f("ck_assets_assigned_to_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('ordered', 'in_stock', 'kitting', 'ready', 'assigned', 'on_loan', 'returned', 'wiped', 'repair', 'retired')",
            name=op.f("ck_assets_status"),
        ),
        sa.CheckConstraint(
            "type IN ('laptop', 'desktop', 'smartphone', 'tablet', 'monitor', 'printer')",
            name=op.f("ck_assets_type"),
        ),
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name=op.f("ck_assets_cost_not_negative")),
        sa.CheckConstraint(
            "warranty_end IS NULL OR purchase_date IS NULL OR warranty_end >= purchase_date",
            name=op.f("ck_assets_warranty_after_purchase"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["employees.id"],
            name=op.f("fk_assets_assigned_to_employees"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("asset_tag", name=op.f("uq_assets_asset_tag")),
        sa.UniqueConstraint("serial_number", name=op.f("uq_assets_serial_number")),
    )
    op.create_index("ix_assets_assigned_to", "assets", ["assigned_to"], unique=False)
    op.create_index("ix_assets_status", "assets", ["status"], unique=False)
    op.create_index("ix_assets_type", "assets", ["type"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=2), server_default="ja", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('ja', 'en')", name=op.f("ck_users_language")),
        sa.CheckConstraint(
            "role IN ('super_admin', 'it_admin', 'manager', 'employee')", name=op.f("ck_users_role")
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_users_employee_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("employee_id", name=op.f("uq_users_employee_id")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_audit_logs_entity_entity_id", "audit_logs", ["entity", "entity_id"], unique=False
    )
    op.create_table(
        "device_details",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("os", sa.String(length=50), nullable=True),
        sa.Column("os_version", sa.String(length=50), nullable=True),
        sa.Column("cpu", sa.String(length=100), nullable=True),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("storage_gb", sa.Integer(), nullable=True),
        sa.Column("mac_address", sa.String(length=17), nullable=True),
        sa.Column("imei", sa.String(length=20), nullable=True),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("carrier", sa.String(length=50), nullable=True),
        sa.Column("sim_iccid", sa.String(length=22), nullable=True),
        sa.Column(
            "autopilot_registered", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("mdm_enrolled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("encryption_on", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("compliance", sa.String(length=20), server_default="unknown", nullable=False),
        sa.Column("last_check_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "compliance IN ('compliant', 'non_compliant', 'unknown')",
            name=op.f("ck_device_details_compliance"),
        ),
        sa.CheckConstraint(
            "ram_gb IS NULL OR ram_gb >= 0", name=op.f("ck_device_details_ram_not_negative")
        ),
        sa.CheckConstraint(
            "storage_gb IS NULL OR storage_gb >= 0",
            name=op.f("ck_device_details_storage_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_device_details_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_device_details")),
    )
    op.create_table(
        "device_loans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("lent_by", sa.Integer(), nullable=False),
        sa.Column("lent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("condition", sa.String(length=20), nullable=True),
        sa.Column("wipe_done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "condition IS NULL OR condition IN ('ok', 'damaged', 'missing_parts')",
            name=op.f("ck_device_loans_condition"),
        ),
        sa.CheckConstraint("due_at > lent_at", name=op.f("ck_device_loans_due_after_lent")),
        sa.CheckConstraint(
            "returned_at IS NULL OR condition IS NOT NULL",
            name=op.f("ck_device_loans_returned_has_condition"),
        ),
        sa.CheckConstraint(
            "returned_at IS NULL OR returned_at >= lent_at",
            name=op.f("ck_device_loans_returned_after_lent"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_device_loans_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_device_loans_employee_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lent_by"],
            ["users.id"],
            name=op.f("fk_device_loans_lent_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_loans")),
    )
    op.create_index("ix_device_loans_due_at", "device_loans", ["due_at"], unique=False)
    op.create_index("ix_device_loans_employee_id", "device_loans", ["employee_id"], unique=False)
    op.create_index(
        "uq_device_loans_one_open_loan_per_asset",
        "device_loans",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.create_table(
        "faq_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("title_en", sa.String(length=200), nullable=False),
        sa.Column("body_en", sa.Text(), nullable=False),
        sa.Column("title_ja", sa.String(length=200), nullable=False),
        sa.Column("body_ja", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_faq_articles_updated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_articles")),
    )
    op.create_index("ix_faq_articles_category", "faq_articles", ["category"], unique=False)
    op.create_table(
        "kitting_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("step_en", sa.String(length=200), nullable=False),
        sa.Column("step_ja", sa.String(length=200), nullable=False),
        sa.Column("done", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("done_by", sa.Integer(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(done AND done_at IS NOT NULL) OR (NOT done AND done_at IS NULL AND done_by IS NULL)",
            name=op.f("ck_kitting_tasks_done_fields_consistent"),
        ),
        sa.CheckConstraint("step_no >= 1", name=op.f("ck_kitting_tasks_step_no_positive")),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_kitting_tasks_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["done_by"],
            ["users.id"],
            name=op.f("fk_kitting_tasks_done_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kitting_tasks")),
    )
    op.create_index("ix_kitting_tasks_asset_id", "kitting_tasks", ["asset_id"], unique=False)
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="web", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('password', 'laptop', 'smartphone', 'tablet', 'vpn', 'email', 'software', 'hardware', 'network', 'account')",
            name=op.f("ck_tickets_category"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')", name=op.f("ck_tickets_priority")
        ),
        sa.CheckConstraint("source IN ('web', 'chatbot')", name=op.f("ck_tickets_source")),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name=op.f("ck_tickets_status"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_tickets_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tickets_assignee_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["employees.id"],
            name=op.f("fk_tickets_requester_id_employees"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index("ix_tickets_asset_id", "tickets", ["asset_id"], unique=False)
    op.create_index("ix_tickets_assignee_id", "tickets", ["assignee_id"], unique=False)
    op.create_index("ix_tickets_requester_id", "tickets", ["requester_id"], unique=False)
    op.create_index("ix_tickets_status", "tickets", ["status"], unique=False)
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("pending_action", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(pending_action IS NULL) = (pending_expires_at IS NULL)",
            name=op.f("ck_chat_sessions_pending_fields_together"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk_chat_sessions_ticket_id_tickets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_sessions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)
    op.create_table(
        "ticket_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_ticket_comments_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk_ticket_comments_ticket_id_tickets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_comments")),
    )
    op.create_index("ix_ticket_comments_ticket_id", "ticket_comments", ["ticket_id"], unique=False)
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')", name=op.f("ck_chat_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all tables in reverse foreign-key order."""
    op.drop_index("ix_chat_messages_session_id_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_ticket_comments_ticket_id", table_name="ticket_comments")
    op.drop_table("ticket_comments")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_requester_id", table_name="tickets")
    op.drop_index("ix_tickets_assignee_id", table_name="tickets")
    op.drop_index("ix_tickets_asset_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("ix_kitting_tasks_asset_id", table_name="kitting_tasks")
    op.drop_table("kitting_tasks")
    op.drop_index("ix_faq_articles_category", table_name="faq_articles")
    op.drop_table("faq_articles")
    op.drop_index(
        "uq_device_loans_one_open_loan_per_asset",
        table_name="device_loans",
        postgresql_where=sa.text("returned_at IS NULL"),
    )
    op.drop_index("ix_device_loans_employee_id", table_name="device_loans")
    op.drop_index("ix_device_loans_due_at", table_name="device_loans")
    op.drop_table("device_loans")
    op.drop_table("device_details")
    op.drop_index("ix_audit_logs_entity_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_index("ix_assets_type", table_name="assets")
    op.drop_index("ix_assets_status", table_name="assets")
    op.drop_index("ix_assets_assigned_to", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_kitting_templates_device_type", table_name="kitting_templates")
    op.drop_table("kitting_templates")
    op.drop_index("ix_employees_department", table_name="employees")
    op.drop_table("employees")
