from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event_impact import ChangeEventImpact
    from app.models.monitor import Monitor


class ContextFeature(Base):
    __tablename__ = "context_features"
    __table_args__ = (
        CheckConstraint(
            "feature_type IN ('road', 'building', 'waterway', 'administrative')",
            name="ck_context_features_feature_type",
        ),
        UniqueConstraint(
            "monitor_id",
            "provider",
            "provider_feature_id",
            "feature_type",
            name="uq_context_features_monitor_provider_feature_type",
        ),
        Index("ix_context_features_monitor_id", "monitor_id"),
        Index("ix_context_features_provider", "provider"),
        Index("ix_context_features_feature_type", "feature_type"),
        Index("ix_context_features_feature_subtype", "feature_subtype"),
        Index("ix_context_features_fetched_at", "fetched_at"),
        Index("ix_context_features_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_feature_id: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_type: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_subtype: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=False,
    )
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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

    monitor: Mapped[Monitor] = relationship(back_populates="context_features")
    impacts: Mapped[list[ChangeEventImpact]] = relationship(
        back_populates="context_feature",
        passive_deletes=True,
    )

