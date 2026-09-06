from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent
    from app.models.monitor import Monitor
    from app.models.prepared_observation import PreparedObservation


class ChangeAnalysis(Base):
    __tablename__ = "change_analyses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_change_analyses_status",
        ),
        CheckConstraint(
            "before_prepared_id <> after_prepared_id",
            name="ck_change_analyses_distinct_prepared_ids",
        ),
        CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_change_analyses_threshold_range",
        ),
        CheckConstraint(
            "minimum_change_area_m2 >= 0",
            name="ck_change_analyses_minimum_change_area_non_negative",
        ),
        CheckConstraint(
            "changed_pixel_count IS NULL OR changed_pixel_count >= 0",
            name="ck_change_analyses_changed_pixel_count_non_negative",
        ),
        CheckConstraint(
            "valid_pixel_count IS NULL OR valid_pixel_count >= 0",
            name="ck_change_analyses_valid_pixel_count_non_negative",
        ),
        CheckConstraint(
            "changed_fraction IS NULL OR (changed_fraction >= 0 AND changed_fraction <= 1)",
            name="ck_change_analyses_changed_fraction_range",
        ),
        CheckConstraint(
            "changed_area_m2 IS NULL OR changed_area_m2 >= 0",
            name="ck_change_analyses_changed_area_non_negative",
        ),
        UniqueConstraint(
            "monitor_id",
            "before_prepared_id",
            "after_prepared_id",
            "algorithm",
            "algorithm_version",
            "threshold",
            "minimum_change_area_m2",
            name="uq_change_analyses_idempotent_key",
        ),
        Index("ix_change_analyses_monitor_id", "monitor_id"),
        Index("ix_change_analyses_created_at", "created_at"),
        Index("ix_change_analyses_before_prepared_id", "before_prepared_id"),
        Index("ix_change_analyses_after_prepared_id", "after_prepared_id"),
        Index("ix_change_analyses_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    before_prepared_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    after_prepared_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'processing'"),
    )
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    change_score_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_mask_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_comparison_mask_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_change_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    changed_pixel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_pixel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_change_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_change_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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

    monitor: Mapped[Monitor] = relationship(back_populates="change_analyses")
    before_prepared_observation: Mapped[PreparedObservation] = relationship(
        back_populates="before_change_analyses",
        foreign_keys=[before_prepared_id],
    )
    after_prepared_observation: Mapped[PreparedObservation] = relationship(
        back_populates="after_change_analyses",
        foreign_keys=[after_prepared_id],
    )
    change_events: Mapped[list[ChangeEvent]] = relationship(
        back_populates="analysis",
        passive_deletes=True,
    )
