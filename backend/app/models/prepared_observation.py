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
    from app.models.change_analysis import ChangeAnalysis
    from app.models.monitor import Monitor
    from app.models.satellite_observation import SatelliteObservation


class PreparedObservation(Base):
    __tablename__ = "prepared_observations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready', 'failed')",
            name="ck_prepared_observations_status",
        ),
        CheckConstraint(
            "cloud_fraction IS NULL OR (cloud_fraction >= 0 AND cloud_fraction <= 1)",
            name="ck_prepared_observations_cloud_fraction_range",
        ),
        CheckConstraint(
            "valid_fraction IS NULL OR (valid_fraction >= 0 AND valid_fraction <= 1)",
            name="ck_prepared_observations_valid_fraction_range",
        ),
        UniqueConstraint(
            "monitor_id",
            "observation_id",
            name="uq_prepared_observations_monitor_observation",
        ),
        Index("ix_prepared_observations_monitor_id", "monitor_id"),
        Index("ix_prepared_observations_observation_id", "observation_id"),
        Index("ix_prepared_observations_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("satellite_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'processing'"),
    )
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_mask_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cloud_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    nodata_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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

    monitor: Mapped[Monitor] = relationship(back_populates="prepared_observations")
    observation: Mapped[SatelliteObservation] = relationship(back_populates="prepared_observation")
    before_change_analyses: Mapped[list[ChangeAnalysis]] = relationship(
        back_populates="before_prepared_observation",
        foreign_keys="ChangeAnalysis.before_prepared_id",
        passive_deletes=True,
    )
    after_change_analyses: Mapped[list[ChangeAnalysis]] = relationship(
        back_populates="after_prepared_observation",
        foreign_keys="ChangeAnalysis.after_prepared_id",
        passive_deletes=True,
    )
