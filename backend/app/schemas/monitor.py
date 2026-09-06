from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.gis.validation import validate_geojson_polygon

NAME_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 2000
MONITOR_TYPE_MAX_LENGTH = 64


class MonitorStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


def _normalize_required_text(value: str, field_name: str, lower: bool = False) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if lower:
        normalized = normalized.lower()
    return normalized


class GeoJSONPolygon(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def validate_polygon(cls, value: Any) -> dict[str, Any]:
        return validate_geojson_polygon(value)


class MonitorCreate(BaseModel):
    name: str = Field(max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    geometry: GeoJSONPolygon
    monitor_type: str = Field(max_length=MONITOR_TYPE_MAX_LENGTH)
    sensitivity: float = Field(ge=0.0, le=1.0)
    minimum_change_area_m2: float = Field(ge=0.0)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_required_text(value, "name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("monitor_type")
    @classmethod
    def validate_monitor_type(cls, value: str) -> str:
        return _normalize_required_text(value, "monitor_type", lower=True)


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    geometry: GeoJSONPolygon | None = None
    monitor_type: str | None = Field(default=None, max_length=MONITOR_TYPE_MAX_LENGTH)
    sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_change_area_m2: float | None = Field(default=None, ge=0.0)
    status: MonitorStatus | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_required_text(value, "name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("monitor_type")
    @classmethod
    def validate_monitor_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_required_text(value, "monitor_type", lower=True)

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> MonitorUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided for update")
        return self


class MonitorRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    geometry: GeoJSONPolygon
    monitor_type: str
    sensitivity: float
    minimum_change_area_m2: float
    status: MonitorStatus
    created_at: datetime
    updated_at: datetime
    last_analyzed_at: datetime | None

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class GeoJSONPoint(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]

    model_config = ConfigDict(extra="forbid")


class MonitorBoundingBox(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    model_config = ConfigDict(extra="forbid")


class MonitorSpatialSummary(BaseModel):
    monitor_id: UUID
    name: str
    status: MonitorStatus
    geometry_type: str
    srid: int
    area_m2: float
    area_km2: float
    centroid: GeoJSONPoint
    bounding_box: MonitorBoundingBox

    model_config = ConfigDict(extra="forbid")


class MonitorIntersectionRequest(BaseModel):
    geometry: GeoJSONPolygon

    model_config = ConfigDict(extra="forbid")


class MonitorIntersectionResponse(BaseModel):
    monitor_id: UUID
    intersects: bool
    intersection_area_m2: float
    intersection_percentage_of_monitor: float

    model_config = ConfigDict(extra="forbid")
