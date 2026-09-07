from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent
    from app.models.population_feature import PopulationFeature


class ChangeEventPopulationExposure(Base):
    __tablename__ = "change_event_population_exposures"
    __table_args__ = (
        CheckConstraint(
            "intersection_area_m2 >= 0",
            name="ck_ce_pop_exp_intersection_area_nn",
        ),
        CheckConstraint(
            "source_area_m2 > 0",
            name="ck_ce_pop_exp_source_area_pos",
        ),
        CheckConstraint(
            "intersection_fraction >= 0 AND intersection_fraction <= 1",
            name="ck_ce_pop_exp_fraction_range",
        ),
        CheckConstraint(
            "source_population IS NULL OR source_population >= 0",
            name="ck_ce_pop_exp_source_pop_nn",
        ),
        CheckConstraint(
            "estimated_exposed_population IS NULL OR estimated_exposed_population >= 0",
            name="ck_ce_pop_exp_est_pop_nn",
        ),
        UniqueConstraint(
            "event_id",
            "population_feature_id",
            name="uq_ce_pop_exp_event_pop_feat",
        ),
        Index("ix_ce_pop_exp_event_id", "event_id"),
        Index("ix_ce_pop_exp_population_feature_id", "population_feature_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    population_feature_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("population_features.id", ondelete="CASCADE"),
        nullable=False,
    )
    intersection_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    source_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    intersection_fraction: Mapped[float] = mapped_column(Float, nullable=False)
    source_population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_exposed_population: Mapped[float | None] = mapped_column(Float, nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    event: Mapped[ChangeEvent] = relationship(back_populates="population_exposures")
    population_feature: Mapped[PopulationFeature] = relationship(back_populates="exposures")
