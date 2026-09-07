from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import polygonize, unary_union

from app.context.osm import (
    OVERPASS_API_URLS,
    OVERPASS_QUERY_TIMEOUT_SECONDS,
    _build_poly_filter,
    _build_provider_feature_id,
    _coords_from_geometry_nodes,
    _extract_areal_geometry,
    _is_closed_ring,
    _jsonable,
    _make_valid_geometry,
    _normalize_text,
    _parse_timestamp,
    _relation_member_lines,
)

logger = logging.getLogger(__name__)

ENVIRONMENT_PROVIDER_NAME = "openstreetmap"
ENVIRONMENT_DATASET = "osm_environmental_features"
ENVIRONMENT_ATTRIBUTION = "© OpenStreetMap contributors"


class EnvironmentalProviderError(Exception):
    pass


class EnvironmentalProviderLimitExceededError(EnvironmentalProviderError):
    pass


@dataclass(slots=True)
class EnvironmentalFeatureCandidate:
    source_feature_id: str
    feature_type: str
    feature_subtype: str | None
    name: str | None
    designation: str | None
    manager: str | None
    geometry: dict[str, Any]
    properties: dict[str, Any]
    source_updated_at: datetime | None = None


@dataclass(slots=True)
class EnvironmentalFetchResult:
    provider: str
    dataset: str
    dataset_version: str
    attribution: str
    fetched_count: int
    skipped_count: int
    features: list[EnvironmentalFeatureCandidate]


class EnvironmentalProvider(Protocol):
    provider_name: str
    dataset: str
    attribution: str

    def fetch_protected_areas(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> EnvironmentalFetchResult: ...


def _classify_environmental_feature(tags: dict[str, Any]) -> tuple[str, str | None]:
    boundary = _normalize_text(tags.get("boundary"), lower=True)
    leisure = _normalize_text(tags.get("leisure"), lower=True)
    natural = _normalize_text(tags.get("natural"), lower=True)
    landuse = _normalize_text(tags.get("landuse"), lower=True)
    protect_class = _normalize_text(tags.get("protect_class"), lower=True)

    if natural == "wetland":
        return "wetland", _normalize_text(tags.get("wetland"), lower=True) or natural
    if boundary == "national_park" or leisure == "nature_reserve":
        return "park", leisure or boundary
    if landuse == "conservation":
        return "conservation_area", landuse
    if boundary == "protected_area" or protect_class is not None:
        return "protected_area", protect_class or boundary

    return "protected_area", boundary or leisure or natural or landuse or protect_class


class OpenStreetMapEnvironmentalProvider:
    provider_name = ENVIRONMENT_PROVIDER_NAME
    dataset = ENVIRONMENT_DATASET
    attribution = ENVIRONMENT_ATTRIBUTION

    def __init__(
        self,
        *,
        overpass_urls: list[str] | tuple[str, ...] | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if overpass_urls is None:
            overpass_urls = OVERPASS_API_URLS
        self.overpass_urls = [str(url).strip() for url in overpass_urls if str(url).strip()]
        self.timeout_seconds = timeout_seconds

        if not self.overpass_urls:
            raise ValueError("at least one Overpass endpoint must be configured")

    def _post_overpass_query(self, query: str, *, max_features: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None

        for endpoint in self.overpass_urls:
            try:
                response = httpx.post(
                    endpoint,
                    data={"data": query},
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "ARGUS/0.1 (environment refresh)"},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Overpass environment request failed endpoint=%s error=%s", endpoint, exc.__class__.__name__)
                continue

            if response.status_code >= 400:
                last_error = RuntimeError(f"status {response.status_code}")
                logger.warning("Overpass environment non-success endpoint=%s status=%s", endpoint, response.status_code)
                continue

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("Overpass environment invalid JSON endpoint=%s", endpoint)
                continue

            elements = payload.get("elements")
            if not isinstance(elements, list):
                last_error = RuntimeError("elements missing")
                continue

            if len(elements) > max_features:
                raise EnvironmentalProviderLimitExceededError("Environmental provider response exceeded configured limit")

            return [item for item in elements if isinstance(item, dict)]

        raise EnvironmentalProviderError("Environmental provider request failed") from last_error

    @staticmethod
    def _feature_query(filters: list[str]) -> str:
        clauses = "\n  ".join(f"{filter_clause};" for filter_clause in filters)
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];\n"
            f"(\n  {clauses}\n);\n"
            "out tags geom qt;"
        )

    @staticmethod
    def _relation_to_geometry(raw_members: Any) -> Polygon | MultiPolygon | None:
        lines = _relation_member_lines(raw_members)
        if not lines:
            return None

        merged = unary_union(lines)
        polygons = list(polygonize(merged))
        if not polygons:
            return None

        polygon_union = unary_union(polygons)
        return _extract_areal_geometry(polygon_union)

    @staticmethod
    def _way_to_geometry(raw_geometry: Any) -> Polygon | MultiPolygon | None:
        coordinates = _coords_from_geometry_nodes(raw_geometry)
        if not _is_closed_ring(coordinates):
            return None

        try:
            polygon = Polygon(coordinates)
        except Exception:
            return None

        return _extract_areal_geometry(polygon)

    def _normalize_feature(self, element: dict[str, Any]) -> EnvironmentalFeatureCandidate | None:
        tags = element.get("tags")
        if not isinstance(tags, dict):
            return None

        element_type = _normalize_text(element.get("type"), lower=True)
        if element_type not in {"way", "relation"}:
            return None

        source_feature_id = _build_provider_feature_id(element_type, element.get("id"))
        if source_feature_id is None:
            return None

        if element_type == "relation":
            raw_geometry = self._relation_to_geometry(element.get("members"))
        else:
            raw_geometry = self._way_to_geometry(element.get("geometry"))

        if raw_geometry is None:
            return None

        valid_geometry = _make_valid_geometry(raw_geometry)
        if valid_geometry is None:
            return None

        areal_geometry = _extract_areal_geometry(valid_geometry)
        if areal_geometry is None:
            return None

        feature_type, feature_subtype = _classify_environmental_feature(tags)
        designation = _normalize_text(tags.get("designation")) or _normalize_text(tags.get("protect_class"))
        manager = _normalize_text(tags.get("operator")) or _normalize_text(tags.get("owner"))

        properties = {
            "osm_type": element_type,
            "osm_id": element.get("id"),
            "boundary": _normalize_text(tags.get("boundary"), lower=True),
            "leisure": _normalize_text(tags.get("leisure"), lower=True),
            "natural": _normalize_text(tags.get("natural"), lower=True),
            "landuse": _normalize_text(tags.get("landuse"), lower=True),
            "protect_class": _normalize_text(tags.get("protect_class"), lower=True),
            "designation": designation,
            "operator": _normalize_text(tags.get("operator")),
            "owner": _normalize_text(tags.get("owner")),
            "wikidata": _normalize_text(tags.get("wikidata")),
            "provider_attribution": self.attribution,
        }

        return EnvironmentalFeatureCandidate(
            source_feature_id=source_feature_id,
            feature_type=feature_type,
            feature_subtype=feature_subtype,
            name=_normalize_text(tags.get("name")),
            designation=designation,
            manager=manager,
            geometry=_jsonable(mapping(areal_geometry)),
            properties={key: value for key, value in properties.items() if value is not None},
            source_updated_at=_parse_timestamp(element.get("timestamp")),
        )

    def fetch_protected_areas(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> EnvironmentalFetchResult:
        poly = _build_poly_filter(intersects_geometry)
        query = self._feature_query(
            [
                f'way["boundary"="protected_area"](poly:"{poly}")',
                f'relation["boundary"="protected_area"](poly:"{poly}")',
                f'way["boundary"="national_park"](poly:"{poly}")',
                f'relation["boundary"="national_park"](poly:"{poly}")',
                f'way["leisure"="nature_reserve"](poly:"{poly}")',
                f'relation["leisure"="nature_reserve"](poly:"{poly}")',
                f'way["landuse"="conservation"](poly:"{poly}")',
                f'relation["landuse"="conservation"](poly:"{poly}")',
                f'way["natural"="wetland"](poly:"{poly}")',
                f'relation["natural"="wetland"](poly:"{poly}")',
                f'way["protect_class"](poly:"{poly}")',
                f'relation["protect_class"](poly:"{poly}")',
            ]
        )
        elements = self._post_overpass_query(query, max_features=max_features)

        features: list[EnvironmentalFeatureCandidate] = []
        skipped = 0
        seen: set[str] = set()

        for element in elements:
            normalized = self._normalize_feature(element)
            if normalized is None:
                skipped += 1
                continue

            if normalized.source_feature_id in seen:
                continue

            seen.add(normalized.source_feature_id)
            features.append(normalized)

        dataset_version = datetime.now(tz=timezone.utc).date().isoformat()
        logger.info(
            "Fetched environmental features raw=%s normalized=%s skipped=%s",
            len(elements),
            len(features),
            skipped,
        )

        return EnvironmentalFetchResult(
            provider=self.provider_name,
            dataset=self.dataset,
            dataset_version=dataset_version,
            attribution=self.attribution,
            fetched_count=len(features),
            skipped_count=skipped,
            features=features,
        )

