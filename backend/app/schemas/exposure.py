from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.change_event import ChangeEventSeverity
from app.schemas.environment import EnvironmentalExposureSummaryRead
from app.schemas.impact import (
    AdministrativeAreaContext,
    BuildingImpactSummary,
    ContextSignificance,
    RoadImpactSummary,
    WaterwayImpactSummary,
)
from app.schemas.landcover import LandCoverExposureSummaryRead
from app.schemas.population import PopulationExposureSummaryRead
from app.schemas.semantic import ChangeEventSemanticAnalysisRead


class ExposureSignificance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExposureFactorRead(BaseModel):
    factor: str
    value: float
    threshold: float
    met: bool

    model_config = ConfigDict(extra="forbid")


class EventExposureSummaryRead(BaseModel):
    event_id: UUID
    monitor_id: UUID
    analysis_id: UUID
    scientific_severity: ChangeEventSeverity
    population: PopulationExposureSummaryRead
    land_cover: LandCoverExposureSummaryRead
    environment: EnvironmentalExposureSummaryRead
    exposure_significance: ExposureSignificance
    significance_factors: list[ExposureFactorRead]
    computed_at: datetime

    model_config = ConfigDict(extra="forbid")


class EventExposureComputeResponse(BaseModel):
    computed: bool
    summary: EventExposureSummaryRead

    model_config = ConfigDict(extra="forbid")


class AnalysisExposureComputeResponse(BaseModel):
    analysis_id: UUID
    event_count: int = Field(ge=0)
    computed: int = Field(ge=0)
    reused: int = Field(ge=0)
    failed: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class MonitorExposureSummaryRead(BaseModel):
    monitor_id: UUID
    events_with_population_exposure: int = Field(ge=0)
    estimated_total_population_exposure_event_level_sum: float = Field(ge=0)
    events_intersecting_protected_areas: int = Field(ge=0)
    total_protected_area_intersection_m2: float = Field(ge=0)
    events_by_dominant_land_cover: dict[str, int]
    events_by_exposure_significance: dict[str, int]

    model_config = ConfigDict(extra="forbid")


class MonitorDatasetStatusEntryRead(BaseModel):
    category: str
    provider: str
    dataset: str
    dataset_version: str | None
    fetched_at: datetime | None
    feature_count: int = Field(ge=0)
    status: str
    attribution: str | None

    model_config = ConfigDict(extra="forbid")


class MonitorDatasetsRead(BaseModel):
    monitor_id: UUID
    datasets: list[MonitorDatasetStatusEntryRead]

    model_config = ConfigDict(extra="forbid")


class EventIntelligenceRead(BaseModel):
    event_id: UUID
    monitor_id: UUID
    analysis_id: UUID
    scientific_severity: ChangeEventSeverity
    change_confidence: float = Field(ge=0, le=1)
    context_significance: ContextSignificance
    exposure_significance: ExposureSignificance
    roads: RoadImpactSummary
    buildings: BuildingImpactSummary
    waterways: WaterwayImpactSummary
    administrative_areas: list[AdministrativeAreaContext]
    population: PopulationExposureSummaryRead
    land_cover: LandCoverExposureSummaryRead
    environment: EnvironmentalExposureSummaryRead
    significance_factors: list[ExposureFactorRead]
    semantic: ChangeEventSemanticAnalysisRead | None = None

    model_config = ConfigDict(extra="forbid")
