from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent
    from app.models.environmental_feature import EnvironmentalFeature


class ChangeEventEnvironmentalExposure(Base):
    __tablename__ = "change_event_environmental_exposures"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('intersects', 'within_buffer')",
            name="ck_ce_env_exp_rel_type",
        ),
        CheckConstraint(
            "intersection_area_m2 IS NULL OR intersection_area_m2 >= 0",
            name="ck_ce_env_exp_intersection_area_nn",
        ),
        CheckConstraint(
            "intersection_fraction_of_event IS NULL OR "
            "(intersection_fraction_of_event >= 0 AND intersection_fraction_of_event <= 1)",
            name="ck_ce_env_exp_fraction_range",
        ),
        CheckConstraint(
            "distance_m >= 0",
            name="ck_ce_env_exp_distance_nn",
        ),
        UniqueConstraint(
            "event_id",
            "environmental_feature_id",
            "relationship_type",
            name="uq_ce_env_exp_event_feature_rel",
        ),
        Index("ix_ce_env_exp_event_id", "event_id"),
        Index(
            "ix_ce_env_exp_environmental_feature_id",
            "environmental_feature_id",
        ),
        Index("ix_ce_env_exp_relationship_type", "relationship_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    environmental_feature_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("environmental_features.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    intersection_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    intersection_fraction_of_event: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    event: Mapped[ChangeEvent] = relationship(back_populates="environmental_exposures")
    environmental_feature: Mapped[EnvironmentalFeature] = relationship(back_populates="exposures")
