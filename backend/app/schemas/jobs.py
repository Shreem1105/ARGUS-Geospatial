from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisJobType(StrEnum):
    MONITOR_RUN = "monitor_run"
    ANALYSIS = "analysis"
    CONTEXT_REFRESH = "context_refresh"


class AnalysisJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MonitorRunType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class MonitorRunStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    NO_NEW_IMAGERY = "no_new_imagery"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MonitorRunEnqueueRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    lookback_days: int | None = Field(default=None, ge=1, le=365)
    max_cloud_cover: float | None = Field(default=None, ge=0, le=100)
    search_limit: int | None = Field(default=None, ge=1, le=100)
    threshold: float = Field(default=0.12, ge=0, le=1)
    minimum_change_area_m2: float | None = Field(default=None, ge=0)
    impact_nearby_buffer_m: float = Field(default=100.0, gt=0, le=5000)
    environment_nearby_buffer_m: float = Field(default=500.0, gt=0, le=10000)
    auto_context_refresh: bool = False
    auto_population_refresh: bool = False
    auto_land_cover_refresh: bool = False
    auto_environment_refresh: bool = False
    force_reprocess: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_dates(self) -> MonitorRunEnqueueRequest:
        if self.start_date is None and self.end_date is None:
            return self
        if self.start_date is None or self.end_date is None:
            raise ValueError("start_date and end_date must both be provided when overriding search window")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be less than or equal to end_date")
        return self


class AnalysisJobRead(BaseModel):
    id: UUID
    monitor_id: UUID
    job_type: AnalysisJobType
    status: AnalysisJobStatus
    celery_task_id: str | None
    progress_stage: str
    progress_percent: float = Field(ge=0, le=100)
    requested_parameters: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class MonitorRunRead(BaseModel):
    id: UUID
    monitor_id: UUID
    analysis_job_id: UUID
    run_type: MonitorRunType
    status: MonitorRunStatus
    search_window_start: date | None
    search_window_end: date | None
    observations_found: int = Field(ge=0)
    observations_inserted: int = Field(ge=0)
    before_observation_id: UUID | None
    after_observation_id: UUID | None
    before_prepared_id: UUID | None
    after_prepared_id: UUID | None
    analysis_id: UUID | None
    events_generated: int = Field(ge=0)
    semantics_computed: bool
    impacts_computed: bool
    exposures_computed: bool
    progress_log: list[dict[str, Any]]
    requested_parameters: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class MonitorRunEnqueueResponse(BaseModel):
    job: AnalysisJobRead
    run: MonitorRunRead

    model_config = ConfigDict(extra="forbid")


class JobCancelResponse(BaseModel):
    cancelled: bool
    job: AnalysisJobRead

    model_config = ConfigDict(extra="forbid")


class MonitorScheduleWrite(BaseModel):
    enabled: bool = True
    interval_hours: int = Field(default=24, ge=1, le=168)
    lookback_days: int = Field(default=60, ge=1, le=365)
    max_cloud_cover: float | None = Field(default=40.0, ge=0, le=100)
    search_limit: int = Field(default=80, ge=1, le=100)
    auto_context_refresh: bool = False
    auto_population_refresh: bool = False
    auto_land_cover_refresh: bool = False
    auto_environment_refresh: bool = False
    threshold: float = Field(default=0.12, ge=0, le=1)
    minimum_change_area_m2: float | None = Field(default=None, ge=0)
    impact_nearby_buffer_m: float = Field(default=100.0, gt=0, le=5000)
    environment_nearby_buffer_m: float = Field(default=500.0, gt=0, le=10000)

    model_config = ConfigDict(extra="forbid")

    @property
    def cadence_minutes(self) -> int:
        return int(self.interval_hours) * 60


class MonitorScheduleRead(BaseModel):
    monitor_id: UUID
    enabled: bool
    interval_hours: int
    cadence_minutes: int
    lookback_days: int
    max_cloud_cover: float | None
    search_limit: int
    auto_context_refresh: bool
    auto_population_refresh: bool
    auto_land_cover_refresh: bool
    auto_environment_refresh: bool
    threshold: float
    minimum_change_area_m2: float | None
    impact_nearby_buffer_m: float
    environment_nearby_buffer_m: float
    next_run_at: datetime | None
    last_scan_at: datetime | None
    last_run_at: datetime | None
    last_enqueued_job_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class WorkerHealthRead(BaseModel):
    status: str
    redis: str
    celery_worker: str
    detail: str | None = None

    model_config = ConfigDict(extra="forbid")

