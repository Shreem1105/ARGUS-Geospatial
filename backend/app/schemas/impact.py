from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.change_event import ChangeEventSeverity


class ContextSignificance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RoadImpactSummary(BaseModel):
    intersecting_count: int = Field(ge=0)
    intersecting_length_m: float = Field(ge=0)
    nearby_count: int = Field(ge=0)
    nearest_distance_m: float | None = Field(default=None, ge=0)
    classes: dict[str, int]

    model_config = ConfigDict(extra="forbid")


class BuildingImpactSummary(BaseModel):
    intersecting_count: int = Field(ge=0)
    intersection_area_m2: float = Field(ge=0)
    nearby_count: int = Field(ge=0)
    nearest_distance_m: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class WaterwayImpactSummary(BaseModel):
    intersecting_count: int = Field(ge=0)
    intersection_length_m: float = Field(ge=0)
    nearby_count: int = Field(ge=0)
    nearest_distance_m: float | None = Field(default=None, ge=0)
    subtypes: list[str]

    model_config = ConfigDict(extra="forbid")


class AdministrativeAreaContext(BaseModel):
    name: str | None
    admin_level: str | None

    model_config = ConfigDict(extra="forbid")


class EventImpactSummaryRead(BaseModel):
    event_id: UUID
    monitor_id: UUID
    analysis_id: UUID
    scientific_severity: ChangeEventSeverity
    context_significance: ContextSignificance
    impact_relationship_count: int = Field(ge=0)
    roads: RoadImpactSummary
    buildings: BuildingImpactSummary
    waterways: WaterwayImpactSummary
    administrative_areas: list[AdministrativeAreaContext]

    model_config = ConfigDict(extra="forbid")


class EventImpactComputeResponse(BaseModel):
    computed: bool
    summary: EventImpactSummaryRead

    model_config = ConfigDict(extra="forbid")


class AnalysisImpactComputeResponse(BaseModel):
    analysis_id: UUID
    event_count: int = Field(ge=0)
    computed: int = Field(ge=0)
    failed: int = Field(ge=0)
    impact_relationship_count: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class MonitorImpactSummaryRead(BaseModel):
    monitor_id: UUID
    events_with_intersecting_roads: int = Field(ge=0)
    total_intersecting_road_length_m: float = Field(ge=0)
    events_with_intersecting_buildings: int = Field(ge=0)
    unique_intersecting_buildings: int = Field(ge=0)
    total_building_intersection_area_m2: float = Field(ge=0)
    events_near_waterways: int = Field(ge=0)
    administrative_areas_containing_events: list[AdministrativeAreaContext]
    total_impact_relationships: int = Field(ge=0)
    unique_context_features_in_impacts: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")

