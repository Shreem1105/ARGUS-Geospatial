from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent
    from app.models.context_feature import ContextFeature


class ChangeEventImpact(Base):
    __tablename__ = "change_event_impacts"
    __table_args__ = (
        CheckConstraint(
            "impact_type IN ('intersects', 'within_buffer', 'contains')",
            name="ck_change_event_impacts_impact_type",
        ),
        CheckConstraint(
            "intersection_area_m2 IS NULL OR intersection_area_m2 >= 0",
            name="ck_change_event_impacts_intersection_area_non_negative",
        ),
        CheckConstraint(
            "intersection_length_m IS NULL OR intersection_length_m >= 0",
            name="ck_change_event_impacts_intersection_length_non_negative",
        ),
        CheckConstraint(
            "distance_m >= 0",
            name="ck_change_event_impacts_distance_non_negative",
        ),
        UniqueConstraint(
            "event_id",
            "context_feature_id",
            "impact_type",
            name="uq_change_event_impacts_event_feature_impact_type",
        ),
        Index("ix_change_event_impacts_event_id", "event_id"),
        Index("ix_change_event_impacts_context_feature_id", "context_feature_id"),
        Index("ix_change_event_impacts_impact_type", "impact_type"),
        Index(
            "ix_change_event_impacts_intersection_geometry_gist",
            "intersection_geometry",
            postgresql_using="gist",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    context_feature_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("context_features.id", ondelete="CASCADE"),
        nullable=False,
    )
    impact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    intersection_geometry: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
        nullable=True,
    )
    intersection_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    intersection_length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    event: Mapped[ChangeEvent] = relationship(back_populates="impacts")
    context_feature: Mapped[ContextFeature] = relationship(back_populates="impacts")

