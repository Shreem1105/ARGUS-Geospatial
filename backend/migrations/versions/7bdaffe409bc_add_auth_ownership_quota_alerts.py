"""add auth ownership quota alerts

Revision ID: 7bdaffe409bc
Revises: 6d16f204f13f
Create Date: 2026-09-12 13:54:39.190592

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7bdaffe409bc"
down_revision: Union[str, Sequence[str], None] = "6d16f204f13f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"
SYSTEM_USER_EMAIL = "system@argus.local"
SYSTEM_USER_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$ube2FoKQ8h4jhHCOEaJUSg$S1d1Qfe49OJ/oCQaleLUrHHdkRgrorYcaS9QKI0AZis"
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=32), server_default=sa.text("'user'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_is_active", "users", ["is_active"], unique=False)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("uq_users_email", "users", ["email"], unique=True)

    op.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, display_name, role, is_active, is_verified)
            VALUES (CAST(:id AS uuid), :email, :password_hash, 'ARGUS System', 'user', true, false)
            ON CONFLICT (email) DO NOTHING
            """
        ).bindparams(
            sa.bindparam("id", SYSTEM_USER_ID),
            sa.bindparam("email", SYSTEM_USER_EMAIL),
            sa.bindparam("password_hash", SYSTEM_USER_PASSWORD_HASH),
        )
    )

    op.add_column(
        "monitors",
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text(f"'{SYSTEM_USER_ID}'::uuid"),
        ),
    )
    op.add_column(
        "monitors",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_foreign_key(
        "fk_monitors_owner_user_id_users",
        "monitors",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_monitors_owner_user_id", "monitors", ["owner_user_id"], unique=False)
    op.create_index("ix_monitors_is_public", "monitors", ["is_public"], unique=False)

    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_hash", sa.String(length=128), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_refresh_sessions_expires_after_create"),
        sa.ForeignKeyConstraint(["replaced_by"], ["refresh_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_refresh_sessions_jti"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )
    op.create_index("ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"], unique=False)
    op.create_index("ix_refresh_sessions_revoked_at", "refresh_sessions", ["revoked_at"], unique=False)
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "usage_type IN ('monitor_create', 'manual_run', 'observation_search', 'semantic_analysis', 'artifact_export')",
            name="ck_usage_events_usage_type",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_usage_events_quantity_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"], unique=False)
    op.create_index("ix_usage_events_usage_type", "usage_events", ["usage_type"], unique=False)
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"], unique=False)

    op.create_table(
        "user_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_monitors", sa.Integer(), nullable=True),
        sa.Column("max_active_monitors", sa.Integer(), nullable=True),
        sa.Column("max_aoi_area_km2", sa.Float(), nullable=True),
        sa.Column("max_manual_runs_per_day", sa.Integer(), nullable=True),
        sa.Column("max_observation_searches_per_day", sa.Integer(), nullable=True),
        sa.Column("max_semantic_runs_per_day", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("max_monitors IS NULL OR max_monitors >= 1", name="ck_user_quotas_max_monitors_min"),
        sa.CheckConstraint(
            "max_active_monitors IS NULL OR max_active_monitors >= 1",
            name="ck_user_quotas_max_active_monitors_min",
        ),
        sa.CheckConstraint(
            "max_aoi_area_km2 IS NULL OR max_aoi_area_km2 > 0",
            name="ck_user_quotas_max_aoi_area_km2_positive",
        ),
        sa.CheckConstraint(
            "max_manual_runs_per_day IS NULL OR max_manual_runs_per_day >= 1",
            name="ck_user_quotas_max_manual_runs_per_day_min",
        ),
        sa.CheckConstraint(
            "max_observation_searches_per_day IS NULL OR max_observation_searches_per_day >= 1",
            name="ck_user_quotas_max_obs_searches_per_day_min",
        ),
        sa.CheckConstraint(
            "max_semantic_runs_per_day IS NULL OR max_semantic_runs_per_day >= 1",
            name="ck_user_quotas_max_semantic_runs_per_day_min",
        ),
        sa.CheckConstraint(
            "max_concurrent_jobs IS NULL OR max_concurrent_jobs >= 1",
            name="ck_user_quotas_max_concurrent_jobs_min",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_user_quotas_user_id", "user_quotas", ["user_id"], unique=True)

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("in_app_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "minimum_event_severity",
            sa.String(length=16),
            server_default=sa.text("'low'"),
            nullable=False,
        ),
        sa.Column("minimum_semantic_confidence", sa.Float(), nullable=True),
        sa.Column("notify_on_new_event", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notify_on_failed_run", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notify_on_partial_run", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "minimum_event_severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_notification_preferences_min_event_severity",
        ),
        sa.CheckConstraint(
            "minimum_semantic_confidence IS NULL OR (minimum_semantic_confidence >= 0 AND minimum_semantic_confidence <= 1)",
            name="ck_notification_preferences_min_semantic_confidence",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "monitor_id", name="uq_notification_preferences_user_monitor"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"], unique=False)
    op.create_index("ix_notification_preferences_monitor_id", "notification_preferences", ["monitor_id"], unique=False)
    op.create_index(
        "uq_notification_preferences_user_global",
        "notification_preferences",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("monitor_id IS NULL"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("change_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'unread'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(length=24), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "alert_type IN ('new_change_event', 'high_change_evidence', 'semantic_change', 'run_partial', 'run_failed')",
            name="ck_alerts_alert_type",
        ),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high')", name="ck_alerts_severity"),
        sa.CheckConstraint("status IN ('unread', 'read')", name="ck_alerts_status"),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'queued', 'delivered', 'failed', 'disabled')",
            name="ck_alerts_delivery_status",
        ),
        sa.ForeignKeyConstraint(["change_event_id"], ["change_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["monitor_run_id"], ["monitor_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "alert_type",
            "monitor_run_id",
            "change_event_id",
            name="uq_alerts_user_type_run_event",
        ),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"], unique=False)
    op.create_index("ix_alerts_status", "alerts", ["status"], unique=False)
    op.create_index("ix_alerts_monitor_id", "alerts", ["monitor_id"], unique=False)
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"], unique=False)
    op.create_index("ix_alerts_change_event_id", "alerts", ["change_event_id"], unique=False)
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alerts_alert_type", table_name="alerts")
    op.drop_index("ix_alerts_change_event_id", table_name="alerts")
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_index("ix_alerts_monitor_id", table_name="alerts")
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index(
        "uq_notification_preferences_user_global",
        table_name="notification_preferences",
        postgresql_where=sa.text("monitor_id IS NULL"),
    )
    op.drop_index("ix_notification_preferences_monitor_id", table_name="notification_preferences")
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")

    op.drop_index("uq_user_quotas_user_id", table_name="user_quotas")
    op.drop_table("user_quotas")

    op.drop_index("ix_usage_events_user_id", table_name="usage_events")
    op.drop_index("ix_usage_events_usage_type", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_table("usage_events")

    op.drop_index("ix_refresh_sessions_user_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_revoked_at", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_expires_at", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")

    op.drop_index("ix_monitors_is_public", table_name="monitors")
    op.drop_index("ix_monitors_owner_user_id", table_name="monitors")
    op.drop_constraint("fk_monitors_owner_user_id_users", "monitors", type_="foreignkey")
    op.drop_column("monitors", "is_public")
    op.drop_column("monitors", "owner_user_id")

    op.drop_index("uq_users_email", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_table("users")
