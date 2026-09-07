from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LandCoverRefreshResponse(BaseModel):
    monitor_id: UUID
    provider: str
    dataset: str
    dataset_version: str
    source_item_id: str
    attribution: str
    fetched: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    fetched_at: datetime
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class LandCoverClassExposureRead(BaseModel):
    class_code: int
    class_name: str
    area_m2: float = Field(ge=0)
    fraction_of_event: float = Field(ge=0, le=1)

    model_config = ConfigDict(extra="forbid")


class LandCoverExposureSummaryRead(BaseModel):
    provider: str
    dataset: str
    dataset_version: str
    dominant_class: str | None
    dominant_fraction: float = Field(ge=0, le=1)
    nodata_fraction: float = Field(ge=0, le=1)
    classes: list[LandCoverClassExposureRead]

    model_config = ConfigDict(extra="forbid")

