"""add monitoring jobs runs schedules

Revision ID: fddca4fde52f
Revises: 4d9a3b8f2c11
Create Date: 2026-09-07 11:16:38.987740

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fddca4fde52f"
down_revision: Union[str, Sequence[str], None] = "4d9a3b8f2c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("progress_stage", sa.String(length=64), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("progress_percent", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("requested_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "job_type IN ('monitor_run', 'analysis', 'context_refresh')",
            name="ck_analysis_jobs_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_analysis_jobs_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_analysis_jobs_progress_percent_range",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id", name="uq_analysis_jobs_celery_task_id"),
    )
    op.create_index("ix_analysis_jobs_created_at", "analysis_jobs", ["created_at"], unique=False)
    op.create_index("ix_analysis_jobs_job_type", "analysis_jobs", ["job_type"], unique=False)
    op.create_index("ix_analysis_jobs_monitor_id", "analysis_jobs", ["monitor_id"], unique=False)
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"], unique=False)
    op.create_index(
        "uq_analysis_jobs_active_monitor_run",
        "analysis_jobs",
        ["monitor_id"],
        unique=True,
        postgresql_where=sa.text("job_type = 'monitor_run' AND status IN ('queued', 'running')"),
    )

    op.create_table(
        "monitor_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("lookback_days", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("max_cloud_cover", sa.Float(), nullable=True),
        sa.Column("search_limit", sa.Integer(), server_default=sa.text("80"), nullable=False),
        sa.Column("auto_context_refresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_population_refresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_land_cover_refresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_environment_refresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("threshold", sa.Float(), server_default=sa.text("0.12"), nullable=False),
        sa.Column("minimum_change_area_m2", sa.Float(), nullable=True),
        sa.Column("impact_nearby_buffer_m", sa.Float(), server_default=sa.text("100"), nullable=False),
        sa.Column("environment_nearby_buffer_m", sa.Float(), server_default=sa.text("500"), nullable=False),
        sa.Column("next_run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_enqueued_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "cadence_minutes >= 60",
            name="ck_monitor_schedules_cadence_minutes_min",
        ),
        sa.CheckConstraint(
            "lookback_days >= 1 AND lookback_days <= 365",
            name="ck_monitor_schedules_lookback_days_range",
        ),
        sa.CheckConstraint(
            "max_cloud_cover IS NULL OR (max_cloud_cover >= 0 AND max_cloud_cover <= 100)",
            name="ck_monitor_schedules_cloud_cover_range",
        ),
        sa.CheckConstraint(
            "search_limit >= 1 AND search_limit <= 100",
            name="ck_monitor_schedules_search_limit_range",
        ),
        sa.CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_monitor_schedules_threshold_range",
        ),
        sa.CheckConstraint(
            "minimum_change_area_m2 IS NULL OR minimum_change_area_m2 >= 0",
            name="ck_monitor_schedules_min_change_area_non_negative",
        ),
        sa.CheckConstraint(
            "impact_nearby_buffer_m > 0 AND impact_nearby_buffer_m <= 5000",
            name="ck_monitor_schedules_impact_buffer_range",
        ),
        sa.CheckConstraint(
            "environment_nearby_buffer_m > 0 AND environment_nearby_buffer_m <= 10000",
            name="ck_monitor_schedules_environment_buffer_range",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_enqueued_job_id"], ["analysis_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("monitor_id", name="uq_monitor_schedules_monitor_id"),
    )
    op.create_index("ix_monitor_schedules_enabled", "monitor_schedules", ["enabled"], unique=False)
    op.create_index("ix_monitor_schedules_last_run_at", "monitor_schedules", ["last_run_at"], unique=False)
    op.create_index("ix_monitor_schedules_next_run_after", "monitor_schedules", ["next_run_after"], unique=False)

    op.create_table(
        "monitor_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_type", sa.String(length=16), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'started'"), nullable=False),
        sa.Column("search_window_start", sa.Date(), nullable=True),
        sa.Column("search_window_end", sa.Date(), nullable=True),
        sa.Column("observations_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("observations_inserted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("before_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("after_observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_prepared_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("after_prepared_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("events_generated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("impacts_computed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("exposures_computed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("progress_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "run_type IN ('manual', 'scheduled')",
            name="ck_monitor_runs_run_type",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'no_new_imagery', 'partial', 'failed', 'cancelled')",
            name="ck_monitor_runs_status",
        ),
        sa.CheckConstraint(
            "observations_found >= 0",
            name="ck_monitor_runs_observations_found_non_negative",
        ),
        sa.CheckConstraint(
            "observations_inserted >= 0",
            name="ck_monitor_runs_observations_inserted_non_negative",
        ),
        sa.CheckConstraint(
            "events_generated >= 0",
            name="ck_monitor_runs_events_generated_non_negative",
        ),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["before_observation_id"], ["satellite_observations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["after_observation_id"], ["satellite_observations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["before_prepared_id"], ["prepared_observations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["after_prepared_id"], ["prepared_observations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["analysis_id"], ["change_analyses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_job_id", name="uq_monitor_runs_analysis_job_id"),
    )
    op.create_index("ix_monitor_runs_completed_at", "monitor_runs", ["completed_at"], unique=False)
    op.create_index("ix_monitor_runs_monitor_id", "monitor_runs", ["monitor_id"], unique=False)
    op.create_index("ix_monitor_runs_started_at", "monitor_runs", ["started_at"], unique=False)
    op.create_index("ix_monitor_runs_status", "monitor_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_monitor_runs_status", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_started_at", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_monitor_id", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_completed_at", table_name="monitor_runs")
    op.drop_table("monitor_runs")

    op.drop_index("ix_monitor_schedules_next_run_after", table_name="monitor_schedules")
    op.drop_index("ix_monitor_schedules_last_run_at", table_name="monitor_schedules")
    op.drop_index("ix_monitor_schedules_enabled", table_name="monitor_schedules")
    op.drop_table("monitor_schedules")

    op.drop_index(
        "uq_analysis_jobs_active_monitor_run",
        table_name="analysis_jobs",
        postgresql_where=sa.text("job_type = 'monitor_run' AND status IN ('queued', 'running')"),
    )
    op.drop_index("ix_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_monitor_id", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_job_type", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_created_at", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
