from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Float, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserQuota(Base):
    __tablename__ = "user_quotas"
    __table_args__ = (
        CheckConstraint(
            "max_monitors IS NULL OR max_monitors >= 1",
            name="ck_user_quotas_max_monitors_min",
        ),
        CheckConstraint(
            "max_active_monitors IS NULL OR max_active_monitors >= 1",
            name="ck_user_quotas_max_active_monitors_min",
        ),
        CheckConstraint(
            "max_aoi_area_km2 IS NULL OR max_aoi_area_km2 > 0",
            name="ck_user_quotas_max_aoi_area_km2_positive",
        ),
        CheckConstraint(
            "max_manual_runs_per_day IS NULL OR max_manual_runs_per_day >= 1",
            name="ck_user_quotas_max_manual_runs_per_day_min",
        ),
        CheckConstraint(
            "max_observation_searches_per_day IS NULL OR max_observation_searches_per_day >= 1",
            name="ck_user_quotas_max_obs_searches_per_day_min",
        ),
        CheckConstraint(
            "max_semantic_runs_per_day IS NULL OR max_semantic_runs_per_day >= 1",
            name="ck_user_quotas_max_semantic_runs_per_day_min",
        ),
        CheckConstraint(
            "max_concurrent_jobs IS NULL OR max_concurrent_jobs >= 1",
            name="ck_user_quotas_max_concurrent_jobs_min",
        ),
        Index("uq_user_quotas_user_id", "user_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    max_monitors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_active_monitors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_aoi_area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_manual_runs_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_observation_searches_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_semantic_runs_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrent_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="quota")
