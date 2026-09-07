from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.monitor import Monitor


class MonitorLandCoverSource(Base):
    __tablename__ = "monitor_land_cover_sources"
    __table_args__ = (
        UniqueConstraint(
            "monitor_id",
            "provider",
            "dataset",
            name="uq_monitor_land_cover_sources_monitor_provider_dataset",
        ),
        Index("ix_monitor_land_cover_sources_monitor_id", "monitor_id"),
        Index("ix_monitor_land_cover_sources_dataset", "dataset"),
        Index("ix_monitor_land_cover_sources_dataset_version", "dataset_version"),
        Index("ix_monitor_land_cover_sources_fetched_at", "fetched_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_key: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_href: Mapped[str] = mapped_column(Text, nullable=False)
    asset_media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
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

    monitor: Mapped[Monitor] = relationship(back_populates="land_cover_sources")

