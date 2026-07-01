"""
Migration 002 — Full feature schema.

Reflects the actual DB state after the v2 refactor:
- Extends users with profile columns
- Creates hosts, host_services, event_logs, app_settings
- Rebuilds check_logs with service_id instead of resource_id
- Drops the old resources table

All ops are guarded so this is safe to run against a DB that is
already fully or partially migrated (the app applied these changes
manually during the debugging phase).

Revision: 002
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


revision = "002_full_feature_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users: add new profile columns ──────────────────────────────────────
    for col, kwargs in [
        ("first_name", dict(type_=sa.String(100), nullable=True)),
        ("last_name",  dict(type_=sa.String(100), nullable=True)),
        ("phone",      dict(type_=sa.String(30),  nullable=True)),
        ("is_active",  dict(type_=sa.Boolean(),   nullable=False, server_default="true")),
        ("deleted_at", dict(type_=sa.DateTime(),  nullable=True)),
    ]:
        if not _column_exists("users", col):
            op.add_column("users", sa.Column(col, **kwargs))

    # ── hosts ────────────────────────────────────────────────────────────────
    if not _table_exists("hosts"):
        op.create_table(
            "hosts",
            sa.Column("id",             sa.Integer(),    primary_key=True, autoincrement=True),
            sa.Column("user_id",        sa.Integer(),    sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name",           sa.String(255),  nullable=False),
            sa.Column("canonical_name", sa.String(255),  nullable=True),
            sa.Column("url",            sa.String(500),  nullable=False),
            sa.Column("ipv4",           sa.String(45),   nullable=True),
            sa.Column("ipv6",           sa.String(100),  nullable=True),
            sa.Column("os",             sa.String(100),  nullable=True),
            sa.Column("location",       sa.String(255),  nullable=True),
            sa.Column("is_active",      sa.Boolean(),    nullable=False, server_default="true"),
            sa.Column("created_at",     sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_hosts_user_id", "hosts", ["user_id"])

    # ── host_services ────────────────────────────────────────────────────────
    if not _table_exists("host_services"):
        op.create_table(
            "host_services",
            sa.Column("id",                 sa.Integer(),    primary_key=True, autoincrement=True),
            sa.Column("host_id",            sa.Integer(),    sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("service_type",       sa.String(10),   nullable=False),
            sa.Column("is_active",          sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("interval_minutes",   sa.Integer(),    nullable=False, server_default="5"),
            sa.Column("status",             sa.String(10),   nullable=False, server_default="pending"),
            sa.Column("last_checked_at",    sa.DateTime(),   nullable=True),
            sa.Column("response_time_ms",   sa.Integer(),    nullable=True),
            sa.Column("ssl_days_remaining", sa.Integer(),    nullable=True),
            sa.Column("last_error",         sa.String(500),  nullable=True),
            sa.Column("created_at",         sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_host_services_host_id", "host_services", ["host_id"])

    # ── check_logs: rebuild with service_id ──────────────────────────────────
    # Old table had resource_id (NOT NULL). We either drop-and-recreate (fresh DB)
    # or patch the existing one (already migrated DB).
    if _table_exists("check_logs"):
        # Make resource_id nullable (safe no-op if already done)
        op.execute("ALTER TABLE check_logs ALTER COLUMN resource_id DROP NOT NULL")
        # Add new columns if missing
        for col, defn in [
            ("service_id",         "INTEGER"),
            ("ssl_days_remaining", "INTEGER"),
            ("error_message",      "TEXT"),
        ]:
            if not _column_exists("check_logs", col):
                op.execute(f"ALTER TABLE check_logs ADD COLUMN IF NOT EXISTS {col} {defn}")
    else:
        op.create_table(
            "check_logs",
            sa.Column("id",                 sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("service_id",         sa.Integer(), sa.ForeignKey("host_services.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("status",             sa.String(10), nullable=False),
            sa.Column("response_time_ms",   sa.Integer(), nullable=True),
            sa.Column("ssl_days_remaining", sa.Integer(), nullable=True),
            sa.Column("error_message",      sa.Text(),    nullable=True),
            sa.Column("checked_at",         sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_check_logs_service_id", "check_logs", ["service_id"])

    # ── event_logs ───────────────────────────────────────────────────────────
    if not _table_exists("event_logs"):
        op.create_table(
            "event_logs",
            sa.Column("id",           sa.Integer(),    primary_key=True, autoincrement=True),
            sa.Column("host_id",      sa.Integer(),    sa.ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("service_type", sa.String(10),   nullable=True),
            sa.Column("event_type",   sa.String(30),   nullable=False),
            sa.Column("message",      sa.Text(),        nullable=False),
            sa.Column("created_at",   sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        )

    # ── app_settings ─────────────────────────────────────────────────────────
    if not _table_exists("app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("id",                 sa.Integer(),    primary_key=True),
            sa.Column("site_url",           sa.String(500),  nullable=True),
            sa.Column("site_name",          sa.String(255),  nullable=True, server_default="Gonitor"),
            sa.Column("monitoring_enabled", sa.Boolean(),    nullable=False, server_default="true"),
            sa.Column("smtp_host",          sa.String(255),  nullable=True),
            sa.Column("smtp_port",          sa.Integer(),    nullable=True, server_default="587"),
            sa.Column("smtp_user",          sa.String(255),  nullable=True),
            sa.Column("smtp_password",      sa.String(255),  nullable=True),
            sa.Column("smtp_from_name",     sa.String(255),  nullable=True),
            sa.Column("smtp_from_email",    sa.String(255),  nullable=True),
            sa.Column("smtp_use_tls",       sa.Boolean(),    server_default="true"),
            sa.Column("notify_via_email",   sa.Boolean(),    server_default="false"),
            sa.Column("notify_via_sms",     sa.Boolean(),    server_default="false"),
            sa.Column("recipient_name",     sa.String(255),  nullable=True),
            sa.Column("recipient_email",    sa.String(255),  nullable=True),
            sa.Column("recipient_phone",    sa.String(30),   nullable=True),
            sa.Column("twilio_sid",         sa.String(255),  nullable=True),
            sa.Column("twilio_auth_token",  sa.String(255),  nullable=True),
            sa.Column("twilio_from_phone",  sa.String(30),   nullable=True),
            sa.Column("updated_at",         sa.DateTime(),   nullable=True),
        )

    # ── resources: data-migrate then drop (if still exists) ─────────────────
    if _table_exists("resources"):
        op.execute("""
            INSERT INTO hosts (user_id, name, url, is_active, created_at)
            SELECT user_id, name, url, is_active, created_at
            FROM resources
            ON CONFLICT DO NOTHING
        """)
        op.execute("""
            INSERT INTO host_services (host_id, service_type, is_active, interval_minutes, status)
            SELECT h.id, 'http', r.is_active, r.interval_minutes,
                   CASE r.status WHEN 'up' THEN 'healthy' WHEN 'down' THEN 'problem' ELSE 'pending' END
            FROM resources r
            JOIN hosts h ON h.url = r.url AND h.user_id = r.user_id
            ON CONFLICT DO NOTHING
        """)
        op.drop_table("resources")


def downgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id",              sa.Integer(),    primary_key=True),
        sa.Column("user_id",         sa.Integer(),    sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name",            sa.String(255),  nullable=False),
        sa.Column("url",             sa.String(500),  nullable=False),
        sa.Column("resource_type",   sa.String(10),   nullable=False, server_default="http"),
        sa.Column("interval_minutes",sa.Integer(),    nullable=False, server_default="5"),
        sa.Column("status",          sa.String(10),   nullable=False, server_default="unknown"),
        sa.Column("last_checked_at", sa.DateTime(),   nullable=True),
        sa.Column("response_time_ms",sa.Integer(),    nullable=True),
        sa.Column("created_at",      sa.DateTime(),   nullable=False, server_default=sa.func.now()),
        sa.Column("is_active",       sa.Boolean(),    nullable=False, server_default="true"),
    )
    op.drop_table("app_settings")
    op.drop_table("event_logs")
    op.drop_table("check_logs")
    op.drop_table("host_services")
    op.drop_table("hosts")
    op.drop_column("users", "first_name")
    op.drop_column("users", "last_name")
    op.drop_column("users", "phone")
    op.drop_column("users", "is_active")
    op.drop_column("users", "deleted_at")
