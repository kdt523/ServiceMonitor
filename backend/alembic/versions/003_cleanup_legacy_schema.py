"""
Migration 003 — Finish cleanup of legacy schema remnants.

The DB was patched manually during debugging:
  - resources table still exists (was supposed to be dropped in 002)
  - check_logs still has resource_id column (old FK, now nullable)
  - check_logs.service_id is currently nullable (should be NOT NULL after cleanup)

This migration finishes the job cleanly.

Revision: 003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return name in inspector.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


revision = "003_cleanup_legacy_schema"
down_revision = "002_full_feature_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop resource_id FK + index from check_logs FIRST
    #    (resources table can't be dropped while this FK still references it)
    if _column_exists("check_logs", "resource_id"):
        try:
            op.drop_constraint(
                "check_logs_resource_id_fkey", "check_logs", type_="foreignkey"
            )
        except Exception:
            pass
        try:
            op.drop_index("ix_check_logs_resource_id", table_name="check_logs")
        except Exception:
            pass
        op.drop_column("check_logs", "resource_id")

    # 2. Now it's safe to drop resources
    if _table_exists("resources"):
        op.drop_table("resources")

    # 3. Make service_id NOT NULL now that resource_id is gone
    #    First clean up any orphan rows written before the column existed
    op.execute("DELETE FROM check_logs WHERE service_id IS NULL")
    op.alter_column(
        "check_logs", "service_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # 4. Add the service_id index if missing
    try:
        op.create_index(
            "ix_check_logs_service_id", "check_logs", ["service_id"]
        )
    except Exception:
        pass  # already exists


def downgrade() -> None:
    # Re-add resource_id as nullable (data is lost)
    op.add_column(
        "check_logs",
        sa.Column("resource_id", sa.Integer(), nullable=True),
    )
    op.alter_column(
        "check_logs", "service_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
