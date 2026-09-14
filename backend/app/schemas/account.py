from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserQuotaLimitsRead(BaseModel):
    max_monitors: int | None
    max_active_monitors: int | None
    max_aoi_area_km2: float | None
    max_manual_runs_per_day: int | None
    max_observation_searches_per_day: int | None
    max_semantic_runs_per_day: int | None
    max_concurrent_jobs: int | None

    model_config = ConfigDict(extra="forbid")


class UserQuotaUsageRead(BaseModel):
    monitor_count: int
    active_monitor_count: int
    manual_runs_today: int
    observation_searches_today: int
    semantic_runs_today: int
    concurrent_jobs: int

    model_config = ConfigDict(extra="forbid")


class UserQuotaRemainingRead(BaseModel):
    remaining_monitors: int | None
    remaining_active_monitors: int | None
    remaining_manual_runs_today: int | None
    remaining_observation_searches_today: int | None
    remaining_semantic_runs_today: int | None
    remaining_concurrent_jobs: int | None

    model_config = ConfigDict(extra="forbid")


class AccountQuotaRead(BaseModel):
    user_id: UUID
    role: str
    limits: UserQuotaLimitsRead
    usage: UserQuotaUsageRead
    remaining: UserQuotaRemainingRead
    resets_at_utc: datetime

    model_config = ConfigDict(extra="forbid")


class AccountUsageRead(BaseModel):
    user_id: UUID
    usage_today: dict[str, int]
    generated_at: datetime

    model_config = ConfigDict(extra="forbid")


class NotificationPreferenceRead(BaseModel):
    id: UUID
    user_id: UUID
    monitor_id: UUID | None
    in_app_enabled: bool
    email_enabled: bool
    minimum_event_severity: str
    minimum_semantic_confidence: float | None
    notify_on_new_event: bool
    notify_on_failed_run: bool
    notify_on_partial_run: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class NotificationPreferenceUpdateRequest(BaseModel):
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    minimum_event_severity: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    minimum_semantic_confidence: float | None = Field(default=None, ge=0, le=1)
    notify_on_new_event: bool | None = None
    notify_on_failed_run: bool | None = None
    notify_on_partial_run: bool | None = None

    model_config = ConfigDict(extra="forbid")


class AdminUserRead(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class UserQuotaOverrideWrite(BaseModel):
    max_monitors: int | None = Field(default=None, ge=1)
    max_active_monitors: int | None = Field(default=None, ge=1)
    max_aoi_area_km2: float | None = Field(default=None, gt=0)
    max_manual_runs_per_day: int | None = Field(default=None, ge=1)
    max_observation_searches_per_day: int | None = Field(default=None, ge=1)
    max_semantic_runs_per_day: int | None = Field(default=None, ge=1)
    max_concurrent_jobs: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")
