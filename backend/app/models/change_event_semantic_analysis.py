from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_analysis import ChangeAnalysis
    from app.models.change_event import ChangeEvent
    from app.models.prepared_observation import PreparedObservation


class ChangeEventSemanticAnalysis(Base):
    __tablename__ = "change_event_semantic_analyses"
    __table_args__ = (
        CheckConstraint(
            "semantic_label IN ("
            "'vegetation_decrease',"
            "'vegetation_increase',"
            "'built_area_increase',"
            "'built_area_decrease',"
            "'water_expansion',"
            "'water_contraction',"
            "'bare_ground_increase',"
            "'bare_ground_decrease',"
            "'mixed_change',"
            "'uncertain'"
            ")",
            name="ck_change_event_semantic_analyses_label",
        ),
        CheckConstraint(
            "semantic_confidence >= 0 AND semantic_confidence <= 1",
            name="ck_change_event_semantic_analyses_confidence_range",
        ),
        CheckConstraint(
            "valid_pixel_coverage IS NULL OR (valid_pixel_coverage >= 0 AND valid_pixel_coverage <= 1)",
            name="ck_change_event_semantic_analyses_valid_pixel_coverage_range",
        ),
        CheckConstraint(
            "embedding_distance IS NULL OR embedding_distance >= 0",
            name="ck_change_event_semantic_emb_dist_non_negative",
        ),
        UniqueConstraint(
            "change_event_id",
            "model_name",
            "model_version",
            "inference_method",
            name="uq_change_event_semantic_analyses_event_model_version_method",
        ),
        Index("ix_change_event_semantic_analyses_event_id", "change_event_id"),
        Index("ix_change_event_semantic_analyses_analysis_id", "change_analysis_id"),
        Index("ix_change_event_semantic_analyses_semantic_label", "semantic_label"),
        Index("ix_change_event_semantic_analyses_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    change_event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    change_analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    before_prepared_observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    after_prepared_observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prepared_observations.id", ondelete="CASCADE"),
        nullable=False,
    )

    semantic_label: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    inference_method: Mapped[str] = mapped_column(String(64), nullable=False)

    before_land_cover: Mapped[str | None] = mapped_column(String(128), nullable=True)
    after_land_cover: Mapped[str | None] = mapped_column(String(128), nullable=True)

    before_ndvi_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_ndvi_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndvi_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    before_ndwi_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_ndwi_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    ndwi_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    before_nbr_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_nbr_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    nbr_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    before_built_up_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_built_up_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    built_up_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    embedding_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_pixel_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)

    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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

    change_event: Mapped[ChangeEvent] = relationship(back_populates="semantic_analyses")
    change_analysis: Mapped[ChangeAnalysis] = relationship(back_populates="semantic_analyses")
    before_prepared_observation: Mapped[PreparedObservation] = relationship(
        back_populates="before_semantic_analyses",
        foreign_keys=[before_prepared_observation_id],
    )
    after_prepared_observation: Mapped[PreparedObservation] = relationship(
        back_populates="after_semantic_analyses",
        foreign_keys=[after_prepared_observation_id],
    )
