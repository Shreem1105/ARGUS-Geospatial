from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, DateTime, Float, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_analysis import ChangeAnalysis
    from app.models.change_event import ChangeEvent
    from app.models.context_feature import ContextFeature
    from app.models.prepared_observation import PreparedObservation
    from app.models.satellite_observation import SatelliteObservation


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint(
            "minimum_change_area_m2 >= 0",
            name="ck_monitors_minimum_change_area_m2_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    monitor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sensitivity: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_change_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'active'"),
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
    last_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    observations: Mapped[list[SatelliteObservation]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    prepared_observations: Mapped[list[PreparedObservation]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    change_analyses: Mapped[list[ChangeAnalysis]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    change_events: Mapped[list[ChangeEvent]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    context_features: Mapped[list[ContextFeature]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
