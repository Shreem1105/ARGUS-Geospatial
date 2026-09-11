from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SemanticLabel(StrEnum):
    VEGETATION_DECREASE = "vegetation_decrease"
    VEGETATION_INCREASE = "vegetation_increase"
    BUILT_AREA_INCREASE = "built_area_increase"
    BUILT_AREA_DECREASE = "built_area_decrease"
    WATER_EXPANSION = "water_expansion"
    WATER_CONTRACTION = "water_contraction"
    BARE_GROUND_INCREASE = "bare_ground_increase"
    BARE_GROUND_DECREASE = "bare_ground_decrease"
    MIXED_CHANGE = "mixed_change"
    UNCERTAIN = "uncertain"


class ChangeEventSemanticAnalysisRead(BaseModel):
    id: UUID
    change_event_id: UUID
    change_analysis_id: UUID
    before_prepared_observation_id: UUID
    after_prepared_observation_id: UUID
    semantic_label: SemanticLabel
    semantic_confidence: float = Field(ge=0, le=1)
    abstained: bool
    model_name: str
    model_version: str
    inference_method: str
    before_land_cover: str | None
    after_land_cover: str | None
    before_ndvi_mean: float | None
    after_ndvi_mean: float | None
    ndvi_delta: float | None
    before_ndwi_mean: float | None
    after_ndwi_mean: float | None
    ndwi_delta: float | None
    before_nbr_mean: float | None
    after_nbr_mean: float | None
    nbr_delta: float | None
    before_built_up_score: float | None
    after_built_up_score: float | None
    built_up_delta: float | None
    embedding_distance: float | None = Field(default=None, ge=0)
    valid_pixel_coverage: float | None = Field(default=None, ge=0, le=1)
    explanation: list[str]
    evidence: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class EventSemanticComputeResponse(BaseModel):
    computed: bool
    summary: ChangeEventSemanticAnalysisRead

    model_config = ConfigDict(extra="forbid")


class AnalysisSemanticComputeResponse(BaseModel):
    analysis_id: UUID
    event_count: int = Field(ge=0)
    computed: int = Field(ge=0)
    reused: int = Field(ge=0)
    failed: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)

    model_config = ConfigDict(extra="forbid")
