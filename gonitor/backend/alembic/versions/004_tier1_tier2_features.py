"""
Migration 004 — Tier 1 & Tier 2 features.

Adds:
  - host_services: port, keyword_check, custom_headers columns
  - check_logs: host_id column (FK to hosts)
  - app_settings: webhook_url, webhook_enabled columns
  - New table: incidents (downtime tracking)
  - Backfills check_logs.host_id from host_services.host_id

Revision: 004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "004_tier1_tier2_features"
down_revision = "003_cleanup_legacy_schema"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # ── host_services: new columns ───────────────────────────────────────
    if not _column_exists("host_services", "port"):
        op.add_column("host_services", sa.Column("port", sa.Integer(), nullable=True))

    if not _column_exists("host_services", "keyword_check"):
        op.add_column("host_services", sa.Column("keyword_check", sa.Text(), nullable=True))

    if not _column_exists("host_services", "custom_headers"):
        op.add_column("host_services", sa.Column("custom_headers", sa.JSON(), nullable=True))

    # Widen service_type from VARCHAR(10) to VARCHAR(20)
    op.alter_column(
        "host_services", "service_type",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=False,
    )

    # ── check_logs: host_id column ───────────────────────────────────────
    if not _column_exists("check_logs", "host_id"):
        op.add_column(
            "check_logs",
            sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True),
        )
        op.create_index("ix_check_logs_host_id", "check_logs", ["host_id"])

    # Backfill check_logs.host_id from host_services.host_id
    op.execute("""
        UPDATE check_logs cl
        SET host_id = hs.host_id
        FROM host_services hs
        WHERE cl.service_id = hs.id
          AND cl.host_id IS NULL
    """)

    # ── event_logs: widen service_type ────────────────────────────────────
    op.alter_column(
        "event_logs", "service_type",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=True,
    )

    # ── app_settings: webhook columns ────────────────────────────────────
    if not _column_exists("app_settings", "webhook_url"):
        op.add_column("app_settings", sa.Column("webhook_url", sa.String(500), nullable=True))

    if not _column_exists("app_settings", "webhook_enabled"):
        op.add_column(
            "app_settings",
            sa.Column("webhook_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    # ── incidents table ──────────────────────────────────────────────────
    if not _table_exists("incidents"):
        op.create_table(
            "incidents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("host_service_id", sa.Integer(),
                      sa.ForeignKey("host_services.id", ondelete="CASCADE"), nullable=False),
            sa.Column("host_id", sa.Integer(),
                      sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("service_type", sa.String(20), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("root_status", sa.String(20), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_incidents_host_service_id", "incidents", ["host_service_id"])
        op.create_index("ix_incidents_host_id", "incidents", ["host_id"])
        op.create_index("ix_incidents_started_at", "incidents", ["started_at"])


def downgrade() -> None:
    # Drop incidents table
    op.drop_index("ix_incidents_started_at", table_name="incidents")
    op.drop_index("ix_incidents_host_id", table_name="incidents")
    op.drop_index("ix_incidents_host_service_id", table_name="incidents")
    op.drop_table("incidents")

    # Remove webhook columns
    op.drop_column("app_settings", "webhook_enabled")
    op.drop_column("app_settings", "webhook_url")

    # Revert event_logs service_type
    op.alter_column(
        "event_logs", "service_type",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=True,
    )

    # Remove check_logs.host_id
    op.drop_index("ix_check_logs_host_id", table_name="check_logs")
    op.drop_column("check_logs", "host_id")

    # Revert host_services
    op.alter_column(
        "host_services", "service_type",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=False,
    )
    op.drop_column("host_services", "custom_headers")
    op.drop_column("host_services", "keyword_check")
    op.drop_column("host_services", "port")
