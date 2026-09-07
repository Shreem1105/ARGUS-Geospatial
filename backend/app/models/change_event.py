from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_analysis import ChangeAnalysis
    from app.models.change_event_environmental_exposure import ChangeEventEnvironmentalExposure
    from app.models.change_event_land_cover_exposure import ChangeEventLandCoverExposure
    from app.models.change_event_population_exposure import ChangeEventPopulationExposure
    from app.models.change_event_impact import ChangeEventImpact
    from app.models.monitor import Monitor


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "area_m2 >= 0",
            name="ck_change_events_area_m2_non_negative",
        ),
        CheckConstraint(
            "perimeter_m >= 0",
            name="ck_change_events_perimeter_m_non_negative",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_change_events_confidence_range",
        ),
        CheckConstraint(
            "pixel_count > 0",
            name="ck_change_events_pixel_count_positive",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_change_events_severity",
        ),
        CheckConstraint(
            "status IN ('new', 'reviewed', 'dismissed', 'confirmed')",
            name="ck_change_events_status",
        ),
        Index("ix_change_events_monitor_id", "monitor_id"),
        Index("ix_change_events_analysis_id", "analysis_id"),
        Index("ix_change_events_first_detected_at", "first_detected_at"),
        Index("ix_change_events_severity", "severity"),
        Index("ix_change_events_status", "status"),
        Index(
            "ix_change_events_geometry_gist",
            "geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    perimeter_m: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    mean_change_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_change_score: Mapped[float] = mapped_column(Float, nullable=False)
    mean_abs_delta_ndvi: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_spectral_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'new'"))
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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

    monitor: Mapped[Monitor] = relationship(back_populates="change_events")
    analysis: Mapped[ChangeAnalysis] = relationship(back_populates="change_events")
    impacts: Mapped[list[ChangeEventImpact]] = relationship(
        back_populates="event",
        passive_deletes=True,
    )
    population_exposures: Mapped[list[ChangeEventPopulationExposure]] = relationship(
        back_populates="event",
        passive_deletes=True,
    )
    land_cover_exposures: Mapped[list[ChangeEventLandCoverExposure]] = relationship(
        back_populates="event",
        passive_deletes=True,
    )
    environmental_exposures: Mapped[list[ChangeEventEnvironmentalExposure]] = relationship(
        back_populates="event",
        passive_deletes=True,
    )
