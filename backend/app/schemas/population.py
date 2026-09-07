from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PopulationRefreshResponse(BaseModel):
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


class PopulationExposureUnitRead(BaseModel):
    source_feature_id: str
    name: str | None
    source_population: int | None = Field(default=None, ge=0)
    intersection_area_m2: float = Field(ge=0)
    source_area_m2: float = Field(gt=0)
    intersection_fraction: float = Field(ge=0, le=1)
    estimated_exposed_population: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class PopulationExposureSummaryRead(BaseModel):
    method: Literal["areal_weighting"]
    dataset: str
    dataset_version: str
    intersecting_units: int = Field(ge=0)
    estimated_exposed_population: float = Field(ge=0)
    largest_population_overlap: PopulationExposureUnitRead | None
    units: list[PopulationExposureUnitRead]

    model_config = ConfigDict(extra="forbid")

