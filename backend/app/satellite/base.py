from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class SatelliteProviderError(Exception):
    pass


@dataclass(slots=True)
class SatelliteSearchResult:
    provider: str
    collection: str
    observations: list[dict[str, Any]]
    skipped_count: int


class SatelliteProvider(Protocol):
    provider_name: str

    def search_sentinel2_observations(
        self,
        *,
        intersects_geometry: dict[str, Any],
        start_datetime: datetime,
        end_datetime: datetime,
        max_cloud_cover: float | None,
        limit: int,
    ) -> SatelliteSearchResult: ...
