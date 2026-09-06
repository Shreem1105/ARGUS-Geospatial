from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ObservationSearchRequest(BaseModel):
    start_date: date
    end_date: date
    max_cloud_cover: float | None = Field(default=None, ge=0, le=100)
    limit: int = Field(default=20, ge=1, le=100)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_date_order(self) -> ObservationSearchRequest:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be less than or equal to end_date")
        return self

    def to_datetime_range(self) -> tuple[datetime, datetime]:
        start_datetime = datetime.combine(self.start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_datetime = datetime.combine(self.end_date, datetime.max.time(), tzinfo=timezone.utc)
        return start_datetime, end_datetime


class ObservationAsset(BaseModel):
    href: str
    media_type: str | None = None
    roles: list[str] | None = None
    title: str | None = None

    model_config = ConfigDict(extra="ignore")


class SatelliteObservationRead(BaseModel):
    id: UUID
    monitor_id: UUID
    provider: str
    collection: str
    item_id: str
    platform: str | None
    sensor: str | None
    acquired_at: datetime
    cloud_cover: float | None
    geometry: dict[str, Any]
    bbox: list[float] | None
    thumbnail_url: str | None
    assets: dict[str, ObservationAsset]
    metadata: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class ObservationSearchResponse(BaseModel):
    monitor_id: UUID
    provider: str
    collection: str
    count: int
    inserted_count: int
    skipped_count: int
    observations: list[SatelliteObservationRead]

    model_config = ConfigDict(extra="forbid")
