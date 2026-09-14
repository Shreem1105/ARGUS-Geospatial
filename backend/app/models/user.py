from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.monitor import Monitor
    from app.models.notification_preference import NotificationPreference
    from app.models.refresh_session import RefreshSession
    from app.models.usage_event import UsageEvent
    from app.models.user_quota import UserQuota


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        Index("uq_users_email", "email", unique=True),
        Index("ix_users_role", "role"),
        Index("ix_users_is_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'user'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    monitors: Mapped[list[Monitor]] = relationship(back_populates="owner")
    refresh_sessions: Mapped[list[RefreshSession]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    quota: Mapped[UserQuota | None] = relationship(
        back_populates="user",
        uselist=False,
        passive_deletes=True,
    )
    usage_events: Mapped[list[UsageEvent]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    alerts: Mapped[list[Alert]] = relationship(back_populates="user", passive_deletes=True)
    notification_preferences: Mapped[list[NotificationPreference]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
