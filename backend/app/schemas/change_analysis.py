from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChangeAnalysisStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChangeAnalysisCreateRequest(BaseModel):
    before_prepared_id: UUID
    after_prepared_id: UUID
    threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    minimum_change_area_m2: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_distinct_prepared_ids(self) -> ChangeAnalysisCreateRequest:
        if self.before_prepared_id == self.after_prepared_id:
            raise ValueError("before_prepared_id and after_prepared_id must differ")
        return self


class ChangeAnalysisAutoRequest(BaseModel):
    before_start_date: date
    before_end_date: date
    after_start_date: date
    after_end_date: date
    max_local_cloud_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    minimum_change_area_m2: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_date_windows(self) -> ChangeAnalysisAutoRequest:
        if self.before_start_date > self.before_end_date:
            raise ValueError("before_start_date must be less than or equal to before_end_date")
        if self.after_start_date > self.after_end_date:
            raise ValueError("after_start_date must be less than or equal to after_end_date")
        return self


class ChangeAnalysisRead(BaseModel):
    id: UUID
    monitor_id: UUID
    before_prepared_id: UUID
    after_prepared_id: UUID
    status: ChangeAnalysisStatus
    algorithm: str
    algorithm_version: str
    change_score_uri: str | None
    change_mask_uri: str | None
    valid_comparison_mask_uri: str | None
    preview_uri: str | None
    threshold: float
    minimum_change_area_m2: float
    changed_pixel_count: int | None
    valid_pixel_count: int | None
    changed_fraction: float | None
    changed_area_m2: float | None
    mean_change_score: float | None
    max_change_score: float | None
    statistics: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")
