from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob
    from app.models.monitor import Monitor


class MonitorSchedule(Base):
    __tablename__ = "monitor_schedules"
    __table_args__ = (
        CheckConstraint(
            "cadence_minutes >= 60",
            name="ck_monitor_schedules_cadence_minutes_min",
        ),
        CheckConstraint(
            "lookback_days >= 1 AND lookback_days <= 365",
            name="ck_monitor_schedules_lookback_days_range",
        ),
        CheckConstraint(
            "max_cloud_cover IS NULL OR (max_cloud_cover >= 0 AND max_cloud_cover <= 100)",
            name="ck_monitor_schedules_cloud_cover_range",
        ),
        CheckConstraint(
            "search_limit >= 1 AND search_limit <= 100",
            name="ck_monitor_schedules_search_limit_range",
        ),
        CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_monitor_schedules_threshold_range",
        ),
        CheckConstraint(
            "minimum_change_area_m2 IS NULL OR minimum_change_area_m2 >= 0",
            name="ck_monitor_schedules_min_change_area_non_negative",
        ),
        CheckConstraint(
            "impact_nearby_buffer_m > 0 AND impact_nearby_buffer_m <= 5000",
            name="ck_monitor_schedules_impact_buffer_range",
        ),
        CheckConstraint(
            "environment_nearby_buffer_m > 0 AND environment_nearby_buffer_m <= 10000",
            name="ck_monitor_schedules_environment_buffer_range",
        ),
        UniqueConstraint("monitor_id", name="uq_monitor_schedules_monitor_id"),
        Index("ix_monitor_schedules_enabled", "enabled"),
        Index("ix_monitor_schedules_next_run_after", "next_run_after"),
        Index("ix_monitor_schedules_last_run_at", "last_run_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    max_cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("80"))
    auto_context_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    auto_population_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    auto_land_cover_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    auto_environment_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    threshold: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.12"))
    minimum_change_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_nearby_buffer_m: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("100"))
    environment_nearby_buffer_m: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("500"))
    next_run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_enqueued_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analysis_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    monitor: Mapped[Monitor] = relationship(back_populates="monitor_schedule")
    last_enqueued_job: Mapped[AnalysisJob | None] = relationship(foreign_keys=[last_enqueued_job_id])

