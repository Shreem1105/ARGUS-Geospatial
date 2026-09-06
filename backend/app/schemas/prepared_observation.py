from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PreparedObservationStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class PrepareObservationRequest(BaseModel):
    force_reprocess: bool = False

    model_config = ConfigDict(extra="forbid")


class ObservationSummary(BaseModel):
    id: UUID
    item_id: str
    provider: str
    collection: str
    platform: str | None
    acquired_at: datetime
    cloud_cover: float | None

    model_config = ConfigDict(extra="forbid")


class PreparedObservationRead(BaseModel):
    id: UUID
    monitor_id: UUID
    observation_id: UUID
    status: PreparedObservationStatus
    storage_uri: str | None
    valid_mask_uri: str | None
    preview_uri: str | None
    crs: str | None
    resolution_m: float | None
    width: int | None
    height: int | None
    band_names: list[str]
    cloud_fraction: float | None
    valid_fraction: float | None
    nodata_value: float | None
    processing_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    observation: ObservationSummary

    model_config = ConfigDict(extra="forbid")
