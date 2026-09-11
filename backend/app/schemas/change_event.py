from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.monitor import GeoJSONPolygon


class ChangeEventSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeEventStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    CONFIRMED = "confirmed"


class GeoJSONPoint(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]

    model_config = ConfigDict(extra="forbid")


class GeoJSONEventPolygon(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]

    model_config = ConfigDict(extra="forbid")


class ChangeEventRead(BaseModel):
    id: UUID
    monitor_id: UUID
    analysis_id: UUID
    geometry: GeoJSONEventPolygon
    centroid: GeoJSONPoint
    area_m2: float = Field(ge=0)
    perimeter_m: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    severity: ChangeEventSeverity
    mean_change_score: float
    max_change_score: float
    mean_abs_delta_ndvi: float | None
    mean_spectral_distance: float | None
    pixel_count: int = Field(ge=1)
    first_detected_at: datetime
    last_detected_at: datetime
    status: ChangeEventStatus
    semantic_label: str | None = None
    semantic_confidence: float | None = Field(default=None, ge=0, le=1)
    semantic_abstained: bool | None = None
    properties: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class ChangeEventGenerationResponse(BaseModel):
    analysis_id: UUID
    count: int = Field(ge=0)
    generated: bool
    events: list[ChangeEventRead]

    model_config = ConfigDict(extra="forbid")


class ChangeEventStatusUpdate(BaseModel):
    status: ChangeEventStatus

    model_config = ConfigDict(extra="forbid")


class ChangeEventBoundingBox(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    model_config = ConfigDict(extra="forbid")


class ChangeEventSpatialSummary(BaseModel):
    monitor_id: UUID
    event_id: UUID
    geometry_type: str
    srid: int
    area_m2: float
    perimeter_m: float
    stored_area_m2: float
    stored_perimeter_m: float
    centroid: GeoJSONPoint
    bounding_box: ChangeEventBoundingBox

    model_config = ConfigDict(extra="forbid")


class ChangeEventIntersectsRequest(BaseModel):
    geometry: GeoJSONPolygon

    model_config = ConfigDict(extra="forbid")


class MonitorEventSummary(BaseModel):
    monitor_id: UUID
    total_events: int
    total_changed_area_m2: float
    mean_confidence: float | None
    by_severity: dict[str, int]
    by_status: dict[str, int]
    latest_detected_at: datetime | None

    model_config = ConfigDict(extra="forbid")
