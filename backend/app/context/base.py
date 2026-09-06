from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


FEATURE_TYPE_ROAD = "road"
FEATURE_TYPE_BUILDING = "building"
FEATURE_TYPE_WATERWAY = "waterway"
FEATURE_TYPE_ADMINISTRATIVE = "administrative"

SUPPORTED_CONTEXT_FEATURE_TYPES: tuple[str, ...] = (
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_WATERWAY,
    FEATURE_TYPE_ADMINISTRATIVE,
)


class ContextProviderError(Exception):
    pass


class ContextProviderLimitExceededError(ContextProviderError):
    pass


@dataclass(slots=True)
class ContextFeatureCandidate:
    provider_feature_id: str
    feature_type: str
    feature_subtype: str | None
    name: str | None
    geometry: dict[str, Any]
    properties: dict[str, Any]
    source_updated_at: datetime | None = None


@dataclass(slots=True)
class ContextFetchResult:
    provider: str
    feature_type: str
    fetched_count: int
    skipped_count: int
    features: list[ContextFeatureCandidate]


class ContextProvider(Protocol):
    provider_name: str
    attribution: str

    def fetch_roads(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult: ...

    def fetch_buildings(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult: ...

    def fetch_waterways(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult: ...

    def fetch_administrative_boundaries(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult: ...
