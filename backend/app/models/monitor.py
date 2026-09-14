from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

DEFAULT_SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

if TYPE_CHECKING:
    from app.models.analysis_job import AnalysisJob
    from app.models.alert import Alert
    from app.models.change_analysis import ChangeAnalysis
    from app.models.change_event import ChangeEvent
    from app.models.environmental_feature import EnvironmentalFeature
    from app.models.monitor_land_cover_source import MonitorLandCoverSource
    from app.models.monitor_run import MonitorRun
    from app.models.monitor_schedule import MonitorSchedule
    from app.models.notification_preference import NotificationPreference
    from app.models.population_feature import PopulationFeature
    from app.models.context_feature import ContextFeature
    from app.models.prepared_observation import PreparedObservation
    from app.models.satellite_observation import SatelliteObservation
    from app.models.user import User


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint(
            "minimum_change_area_m2 >= 0",
            name="ck_monitors_minimum_change_area_m2_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        default=lambda: DEFAULT_SYSTEM_USER_ID,
        server_default=text("'00000000-0000-0000-0000-000000000001'::uuid"),
    )
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
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
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
    owner: Mapped[User] = relationship(back_populates="monitors")
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
    population_features: Mapped[list[PopulationFeature]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    environmental_features: Mapped[list[EnvironmentalFeature]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    land_cover_sources: Mapped[list[MonitorLandCoverSource]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    monitor_runs: Mapped[list[MonitorRun]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    monitor_schedule: Mapped[MonitorSchedule | None] = relationship(
        back_populates="monitor",
        passive_deletes=True,
        uselist=False,
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
    notification_preferences: Mapped[list[NotificationPreference]] = relationship(
        back_populates="monitor",
        passive_deletes=True,
    )
