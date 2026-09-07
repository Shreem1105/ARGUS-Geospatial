from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent


class ChangeEventLandCoverExposure(Base):
    __tablename__ = "change_event_land_cover_exposures"
    __table_args__ = (
        CheckConstraint(
            "area_m2 >= 0",
            name="ck_change_event_land_cover_exposures_area_non_negative",
        ),
        CheckConstraint(
            "fraction_of_event >= 0 AND fraction_of_event <= 1",
            name="ck_change_event_land_cover_exposures_fraction_range",
        ),
        UniqueConstraint(
            "event_id",
            "dataset",
            "dataset_version",
            "class_code",
            name="uq_change_event_land_cover_exposures_event_dataset_class",
        ),
        Index("ix_change_event_land_cover_exposures_event_id", "event_id"),
        Index("ix_change_event_land_cover_exposures_dataset", "dataset"),
        Index("ix_change_event_land_cover_exposures_class_code", "class_code"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    class_code: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(128), nullable=False)
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    fraction_of_event: Mapped[float] = mapped_column(Float, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    event: Mapped[ChangeEvent] = relationship(back_populates="land_cover_exposures")

