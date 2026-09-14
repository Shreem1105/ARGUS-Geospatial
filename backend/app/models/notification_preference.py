from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.monitor import Monitor
    from app.models.user import User


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            "minimum_event_severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_notification_preferences_min_event_severity",
        ),
        CheckConstraint(
            "minimum_semantic_confidence IS NULL OR (minimum_semantic_confidence >= 0 AND minimum_semantic_confidence <= 1)",
            name="ck_notification_preferences_min_semantic_confidence",
        ),
        UniqueConstraint("user_id", "monitor_id", name="uq_notification_preferences_user_monitor"),
        Index(
            "uq_notification_preferences_user_global",
            "user_id",
            unique=True,
            postgresql_where=text("monitor_id IS NULL"),
        ),
        Index("ix_notification_preferences_user_id", "user_id"),
        Index("ix_notification_preferences_monitor_id", "monitor_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=True,
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    minimum_event_severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'low'"))
    minimum_semantic_confidence: Mapped[float | None] = mapped_column(nullable=True)
    notify_on_new_event: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notify_on_failed_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notify_on_partial_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="notification_preferences")
    monitor: Mapped[Monitor | None] = relationship(back_populates="notification_preferences")
