from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.monitor import Monitor
    from app.models.monitor_run import MonitorRun


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('monitor_run', 'analysis', 'context_refresh')",
            name="ck_analysis_jobs_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_analysis_jobs_status",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_analysis_jobs_progress_percent_range",
        ),
        UniqueConstraint(
            "celery_task_id",
            name="uq_analysis_jobs_celery_task_id",
        ),
        Index("ix_analysis_jobs_monitor_id", "monitor_id"),
        Index("ix_analysis_jobs_job_type", "job_type"),
        Index("ix_analysis_jobs_status", "status"),
        Index("ix_analysis_jobs_created_at", "created_at"),
        Index(
            "uq_analysis_jobs_active_monitor_run",
            "monitor_id",
            unique=True,
            postgresql_where=text("job_type = 'monitor_run' AND status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'queued'"))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_stage: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'queued'"))
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    requested_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    monitor: Mapped[Monitor] = relationship(back_populates="analysis_jobs")
    monitor_runs: Mapped[list[MonitorRun]] = relationship(
        back_populates="analysis_job",
        passive_deletes=True,
    )
