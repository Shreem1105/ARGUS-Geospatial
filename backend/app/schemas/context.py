from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContextFeatureType(StrEnum):
    ROAD = "road"
    BUILDING = "building"
    WATERWAY = "waterway"
    ADMINISTRATIVE = "administrative"


class ContextRefreshRequest(BaseModel):
    feature_types: list[ContextFeatureType] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("feature_types")
    @classmethod
    def validate_feature_types(cls, value: list[ContextFeatureType] | None) -> list[ContextFeatureType] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("feature_types must not be empty when provided")

        unique_values: list[ContextFeatureType] = []
        seen: set[str] = set()
        for item in value:
            if item.value in seen:
                continue
            unique_values.append(item)
            seen.add(item.value)
        return unique_values


class ContextFeatureRead(BaseModel):
    id: UUID
    monitor_id: UUID
    provider: str
    provider_feature_id: str
    feature_type: ContextFeatureType
    feature_subtype: str | None
    name: str | None
    geometry: dict[str, Any]
    properties: dict[str, Any]
    source_updated_at: datetime | None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class ContextRefreshResponse(BaseModel):
    monitor_id: UUID
    provider: str
    attribution: str
    fetched: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    by_type: dict[str, int]
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class ContextSummaryRead(BaseModel):
    monitor_id: UUID
    total_features: int = Field(ge=0)
    by_type: dict[str, int]
    road_classes: dict[str, int]
    providers: list[str]
    attribution: str
    last_fetched_at: datetime | None

    model_config = ConfigDict(extra="forbid")

