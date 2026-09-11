from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob
    from app.models.change_analysis import ChangeAnalysis
    from app.models.monitor import Monitor
    from app.models.prepared_observation import PreparedObservation
    from app.models.satellite_observation import SatelliteObservation


class MonitorRun(Base):
    __tablename__ = "monitor_runs"
    __table_args__ = (
        CheckConstraint(
            "run_type IN ('manual', 'scheduled')",
            name="ck_monitor_runs_run_type",
        ),
        CheckConstraint(
            "status IN ('started', 'succeeded', 'no_new_imagery', 'partial', 'failed', 'cancelled')",
            name="ck_monitor_runs_status",
        ),
        CheckConstraint(
            "observations_found >= 0",
            name="ck_monitor_runs_observations_found_non_negative",
        ),
        CheckConstraint(
            "observations_inserted >= 0",
            name="ck_monitor_runs_observations_inserted_non_negative",
        ),
        CheckConstraint(
            "events_generated >= 0",
            name="ck_monitor_runs_events_generated_non_negative",
        ),
        UniqueConstraint(
            "analysis_job_id",
            name="uq_monitor_runs_analysis_job_id",
        ),
        Index("ix_monitor_runs_monitor_id", "monitor_id"),
        Index("ix_monitor_runs_status", "status"),
        Index("ix_monitor_runs_started_at", "started_at"),
        Index("ix_monitor_runs_completed_at", "completed_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'manual'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'started'"))
    search_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    search_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    observations_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    observations_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    before_observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_observation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    before_prepared_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_prepared_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    analysis_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    events_generated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    semantics_computed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    impacts_computed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    exposures_computed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    progress_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    requested_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    monitor: Mapped[Monitor] = relationship(back_populates="monitor_runs")
    analysis_job: Mapped[AnalysisJob] = relationship(back_populates="monitor_runs")
    before_observation: Mapped[SatelliteObservation | None] = relationship(
        foreign_keys=[before_observation_id],
    )
    after_observation: Mapped[SatelliteObservation | None] = relationship(
        foreign_keys=[after_observation_id],
    )
    before_prepared: Mapped[PreparedObservation | None] = relationship(
        foreign_keys=[before_prepared_id],
    )
    after_prepared: Mapped[PreparedObservation | None] = relationship(
        foreign_keys=[after_prepared_id],
    )
    analysis: Mapped[ChangeAnalysis | None] = relationship(
        foreign_keys=[analysis_id],
    )
