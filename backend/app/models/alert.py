from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.change_event import ChangeEvent
    from app.models.monitor import Monitor
    from app.models.monitor_run import MonitorRun
    from app.models.user import User


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('new_change_event', 'high_change_evidence', 'semantic_change', 'run_partial', 'run_failed')",
            name="ck_alerts_alert_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_alerts_severity",
        ),
        CheckConstraint(
            "status IN ('unread', 'read')",
            name="ck_alerts_status",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'queued', 'delivered', 'failed', 'disabled')",
            name="ck_alerts_delivery_status",
        ),
        UniqueConstraint(
            "user_id",
            "alert_type",
            "monitor_run_id",
            "change_event_id",
            name="uq_alerts_user_type_run_event",
        ),
        Index("ix_alerts_user_id", "user_id"),
        Index("ix_alerts_monitor_id", "monitor_id"),
        Index("ix_alerts_change_event_id", "change_event_id"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_alert_type", "alert_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitor_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitor_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitor_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_event_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'unread'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'pending'"))
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    user: Mapped[User] = relationship(back_populates="alerts")
    monitor: Mapped[Monitor] = relationship(back_populates="alerts")
    monitor_run: Mapped[MonitorRun | None] = relationship()
    change_event: Mapped[ChangeEvent | None] = relationship()
