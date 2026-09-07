from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentRefreshResponse(BaseModel):
    monitor_id: UUID
    provider: str
    dataset: str
    dataset_version: str
    attribution: str
    fetched: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class EnvironmentalExposureFeatureRead(BaseModel):
    source_feature_id: str
    feature_type: str
    feature_subtype: str | None
    name: str | None
    designation: str | None
    manager: str | None
    relationship_type: str
    intersection_area_m2: float | None = Field(default=None, ge=0)
    intersection_fraction_of_event: float | None = Field(default=None, ge=0, le=1)
    distance_m: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class EnvironmentalExposureSummaryRead(BaseModel):
    provider: str
    dataset: str
    dataset_version: str
    nearby_buffer_m: float = Field(gt=0)
    intersecting_count: int = Field(ge=0)
    intersection_area_m2: float = Field(ge=0)
    protected_area_fraction: float = Field(ge=0, le=1)
    nearby_count: int = Field(ge=0)
    nearest_distance_m: float | None = Field(default=None, ge=0)
    designations: list[str]
    features: list[EnvironmentalExposureFeatureRead]

    model_config = ConfigDict(extra="forbid")

