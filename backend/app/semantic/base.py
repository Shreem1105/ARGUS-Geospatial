from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

SEMANTIC_LABEL_VALUES: tuple[str, ...] = (
    "vegetation_decrease",
    "vegetation_increase",
    "built_area_increase",
    "built_area_decrease",
    "water_expansion",
    "water_contraction",
    "bare_ground_increase",
    "bare_ground_decrease",
    "mixed_change",
    "uncertain",
)

SEMANTIC_MODEL_NAME = "torchgeo_resnet18_sentinel2_rgb_moco"
SEMANTIC_MODEL_VERSION = "resnet18_sentinel2_rgb_moco-e3a335e3"
SEMANTIC_INFERENCE_METHOD = "hybrid_rule_v1"


@dataclass(slots=True)
class EventSpectralEvidence:
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
    valid_pixel_count: int
    total_event_pixel_count: int
    valid_pixel_coverage: float
    before_rgb_patch: np.ndarray | None
    after_rgb_patch: np.ndarray | None
    patch_valid_mask: np.ndarray | None
    index_availability: dict[str, bool]
    notes: list[str]


@dataclass(slots=True)
class EmbeddingEvidence:
    distance: float
    similarity: float
    embedding_dim: int
    input_height: int
    input_width: int
    normalization_mean: tuple[float, float, float]
    normalization_std: tuple[float, float, float]
    device: str
    inference_seconds: float
    model_load_seconds: float


@dataclass(slots=True)
class SemanticInferenceOutcome:
    semantic_label: str
    semantic_confidence: float
    abstained: bool
    explanation: list[str]
    signal_scores: dict[str, float]
    abstention_reasons: list[str]
    diagnostics: dict[str, Any]
