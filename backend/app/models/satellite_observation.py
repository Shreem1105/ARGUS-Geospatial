from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.monitor import Monitor
    from app.models.prepared_observation import PreparedObservation


class SatelliteObservation(Base):
    __tablename__ = "satellite_observations"
    __table_args__ = (
        CheckConstraint(
            "cloud_cover IS NULL OR (cloud_cover >= 0 AND cloud_cover <= 100)",
            name="ck_satellite_observations_cloud_cover_range",
        ),
        UniqueConstraint(
            "monitor_id",
            "provider",
            "collection",
            "item_id",
            name="uq_satellite_observations_monitor_provider_collection_item",
        ),
        Index("ix_satellite_observations_monitor_id", "monitor_id"),
        Index("ix_satellite_observations_acquired_at", "acquired_at"),
        Index("ix_satellite_observations_monitor_acquired_at", "monitor_id", "acquired_at"),
        Index(
            "ix_satellite_observations_geometry_gist",
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
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    collection: Mapped[str] = mapped_column(String(128), nullable=False)
    item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sensor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=False,
    )
    bbox: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    assets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    monitor: Mapped[Monitor] = relationship(back_populates="observations")
    prepared_observation: Mapped[PreparedObservation | None] = relationship(
        back_populates="observation",
        uselist=False,
        passive_deletes=True,
    )
