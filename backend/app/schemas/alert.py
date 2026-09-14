from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AlertRead(BaseModel):
    id: UUID
    user_id: UUID
    monitor_id: UUID
    monitor_run_id: UUID | None
    change_event_id: UUID | None
    alert_type: str
    severity: str
    title: str
    message: str
    status: str
    created_at: datetime
    read_at: datetime | None
    delivery_status: str
    delivery_error: str | None
    metadata: dict[str, object]

    model_config = ConfigDict(extra="forbid")


class AlertUpdateRequest(BaseModel):
    status: str = Field(pattern="^(read|unread)$")

    model_config = ConfigDict(extra="forbid")


class AlertListResponse(BaseModel):
    count: int
    alerts: list[AlertRead]

    model_config = ConfigDict(extra="forbid")
