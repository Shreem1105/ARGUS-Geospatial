from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from shapely import make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
    mapping,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from app.context.base import (
    FEATURE_TYPE_ADMINISTRATIVE,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_WATERWAY,
    ContextFeatureCandidate,
    ContextFetchResult,
    ContextProviderError,
    ContextProviderLimitExceededError,
)
from app.context.normalization import normalize_road_class

logger = logging.getLogger(__name__)

OVERPASS_API_URLS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_QUERY_TIMEOUT_SECONDS = 90
OSM_PROVIDER_NAME = "openstreetmap"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _normalize_text(value: Any, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    normalized = value.strip()
    if not normalized:
        return None

    if lower:
        normalized = normalized.lower()

    return normalized


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = _normalize_text(value)
    if normalized is None:
        return None

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _extract_areal_geometry(geometry: BaseGeometry) -> Polygon | MultiPolygon | None:
    if geometry.is_empty:
        return None

    if isinstance(geometry, Polygon):
        return geometry

    if isinstance(geometry, MultiPolygon):
        return geometry

    if isinstance(geometry, GeometryCollection):
        polygons: list[Polygon] = []
        for child in geometry.geoms:
            areal = _extract_areal_geometry(child)
            if areal is None:
                continue
            if isinstance(areal, Polygon):
                polygons.append(areal)
            else:
                polygons.extend([polygon for polygon in areal.geoms if not polygon.is_empty])

        if not polygons:
            return None
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)

    return None


def _extract_lineal_geometry(geometry: BaseGeometry) -> LineString | MultiLineString | None:
    if geometry.is_empty:
        return None

    if isinstance(geometry, LineString):
        return geometry

    if isinstance(geometry, MultiLineString):
        return geometry

    if isinstance(geometry, GeometryCollection):
        lines: list[LineString] = []
        for child in geometry.geoms:
            lineal = _extract_lineal_geometry(child)
            if lineal is None:
                continue
            if isinstance(lineal, LineString):
                lines.append(lineal)
            else:
                lines.extend([line for line in lineal.geoms if not line.is_empty])

        if not lines:
            return None
        if len(lines) == 1:
            return lines[0]
        return MultiLineString(lines)

    return None


def _make_valid_geometry(geometry: BaseGeometry) -> BaseGeometry | None:
    if geometry.is_empty:
        return None

    if geometry.is_valid:
        return geometry

    repaired = make_valid(geometry)
    if repaired.is_empty:
        return None

    return repaired


def _coords_from_geometry_nodes(raw_geometry: Any) -> list[tuple[float, float]]:
    if not isinstance(raw_geometry, list):
        return []

    coordinates: list[tuple[float, float]] = []
    for node in raw_geometry:
        if not isinstance(node, dict):
            continue
        lon = node.get("lon")
        lat = node.get("lat")
        if isinstance(lon, bool) or isinstance(lat, bool):
            continue
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            continue
        coordinates.append((float(lon), float(lat)))

    return coordinates


def _is_closed_ring(coordinates: list[tuple[float, float]]) -> bool:
    if len(coordinates) < 4:
        return False
    return coordinates[0] == coordinates[-1]


def _relation_member_lines(raw_members: Any) -> list[LineString]:
    if not isinstance(raw_members, list):
        return []

    lines: list[LineString] = []
    for member in raw_members:
        if not isinstance(member, dict):
            continue
        member_coords = _coords_from_geometry_nodes(member.get("geometry"))
        if len(member_coords) < 2:
            continue

        line = LineString(member_coords)
        if line.is_empty or line.length <= 0:
            continue
        lines.append(line)

    return lines


def _build_provider_feature_id(element_type: Any, element_id: Any) -> str | None:
    type_value = _normalize_text(element_type, lower=True)
    if type_value not in {"node", "way", "relation"}:
        return None

    if isinstance(element_id, bool):
        return None

    if isinstance(element_id, (int, float)):
        numeric_id = int(element_id)
        if numeric_id <= 0:
            return None
        return f"{type_value}/{numeric_id}"

    text_id = _normalize_text(element_id)
    if text_id is None:
        return None

    return f"{type_value}/{text_id}"


def _build_poly_filter(intersects_geometry: dict[str, Any]) -> str:
    monitor_geometry = shape(intersects_geometry)

    if isinstance(monitor_geometry, Polygon):
        polygon = monitor_geometry
    elif isinstance(monitor_geometry, MultiPolygon):
        polygon = max(monitor_geometry.geoms, key=lambda item: item.area)
    else:
        raise ContextProviderError("Monitor geometry must be Polygon or MultiPolygon")

    ring = list(polygon.exterior.coords)
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]

    if len(ring) < 3:
        raise ContextProviderError("Monitor polygon ring is invalid")

    return " ".join(f"{latitude:.7f} {longitude:.7f}" for longitude, latitude in ring)


class OpenStreetMapProvider:
    provider_name = OSM_PROVIDER_NAME
    attribution = OSM_ATTRIBUTION

    def __init__(
        self,
        overpass_url: str | None = None,
        overpass_urls: list[str] | tuple[str, ...] | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if overpass_urls is not None:
            normalized_urls = [str(url).strip() for url in overpass_urls if str(url).strip()]
        elif overpass_url is not None:
            normalized_urls = [str(overpass_url).strip()]
        else:
            normalized_urls = list(OVERPASS_API_URLS)

        if not normalized_urls:
            raise ValueError("at least one Overpass endpoint must be configured")

        self.overpass_urls = normalized_urls
        self.timeout_seconds = timeout_seconds

    def _post_overpass_query(self, query: str, *, max_features: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None

        for endpoint in self.overpass_urls:
            try:
                response = httpx.post(
                    endpoint,
                    data={"data": query},
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "ARGUS/0.1 (context refresh)"},
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Overpass request failed endpoint=%s error=%s", endpoint, exc.__class__.__name__)
                continue

            if response.status_code >= 400:
                logger.warning(
                    "Overpass non-success endpoint=%s status=%s",
                    endpoint,
                    response.status_code,
                )
                last_error = RuntimeError(f"status {response.status_code}")
                continue

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("Overpass invalid JSON endpoint=%s", endpoint)
                continue

            elements = payload.get("elements")
            if not isinstance(elements, list):
                last_error = RuntimeError("elements missing")
                logger.warning("Overpass payload missing elements endpoint=%s", endpoint)
                continue

            if len(elements) > max_features:
                raise ContextProviderLimitExceededError("OSM provider response exceeded configured feature limit")

            return [element for element in elements if isinstance(element, dict)]

        raise ContextProviderError("OSM provider request failed") from last_error

    def _feature_query(self, *, filters: list[str]) -> str:
        clauses = "\n  ".join(f"{filter_clause};" for filter_clause in filters)
        return (
            f"[out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];\n"
            f"(\n  {clauses}\n);\n"
            "out tags geom qt;"
        )

    def _relation_to_geometry(
        self,
        *,
        feature_type: str,
        tags: dict[str, Any],
        raw_members: Any,
    ) -> BaseGeometry | None:
        lines = _relation_member_lines(raw_members)
        if not lines:
            return None

        merged = unary_union(lines)

        requires_areal = feature_type in {FEATURE_TYPE_BUILDING, FEATURE_TYPE_ADMINISTRATIVE}
        if feature_type == FEATURE_TYPE_WATERWAY and _normalize_text(tags.get("natural"), lower=True) == "water":
            requires_areal = True

        if requires_areal:
            polygons = list(polygonize(merged))
            if polygons:
                return unary_union(polygons)
            return None

        lineal = _extract_lineal_geometry(merged)
        return lineal

    def _way_to_geometry(
        self,
        *,
        feature_type: str,
        tags: dict[str, Any],
        raw_geometry: Any,
    ) -> BaseGeometry | None:
        coordinates = _coords_from_geometry_nodes(raw_geometry)
        if len(coordinates) < 2:
            return None

        closed_ring = _is_closed_ring(coordinates)

        if feature_type == FEATURE_TYPE_ROAD:
            return LineString(coordinates)

        if feature_type == FEATURE_TYPE_BUILDING:
            if not closed_ring:
                return None
            return Polygon(coordinates)

        if feature_type == FEATURE_TYPE_ADMINISTRATIVE:
            if not closed_ring:
                return None
            return Polygon(coordinates)

        if feature_type == FEATURE_TYPE_WATERWAY:
            natural_value = _normalize_text(tags.get("natural"), lower=True)
            waterway_value = _normalize_text(tags.get("waterway"), lower=True)
            if closed_ring and (natural_value == "water" or waterway_value == "riverbank"):
                return Polygon(coordinates)
            return LineString(coordinates)

        return None

    def _normalize_geometry(
        self,
        *,
        feature_type: str,
        geometry: BaseGeometry,
    ) -> BaseGeometry | None:
        repaired = _make_valid_geometry(geometry)
        if repaired is None:
            return None

        if feature_type in {FEATURE_TYPE_BUILDING, FEATURE_TYPE_ADMINISTRATIVE}:
            areal = _extract_areal_geometry(repaired)
            if areal is None or areal.is_empty or areal.area <= 0:
                return None
            return areal

        if feature_type == FEATURE_TYPE_ROAD:
            lineal = _extract_lineal_geometry(repaired)
            if lineal is None or lineal.is_empty or lineal.length <= 0:
                return None
            return lineal

        if feature_type == FEATURE_TYPE_WATERWAY:
            areal = _extract_areal_geometry(repaired)
            if areal is not None and not areal.is_empty and areal.area > 0:
                return areal

            lineal = _extract_lineal_geometry(repaired)
            if lineal is None or lineal.is_empty or lineal.length <= 0:
                return None
            return lineal

        return None

    def _road_properties(self, *, element_type: str, element_id: Any, tags: dict[str, Any]) -> dict[str, Any]:
        highway = _normalize_text(tags.get("highway"), lower=True)

        properties = {
            "osm_type": element_type,
            "osm_id": element_id,
            "name": _normalize_text(tags.get("name")),
            "highway": highway,
            "road_class": normalize_road_class(highway),
            "lanes": _normalize_text(tags.get("lanes")),
            "maxspeed": _normalize_text(tags.get("maxspeed")),
            "bridge": _normalize_text(tags.get("bridge"), lower=True),
            "tunnel": _normalize_text(tags.get("tunnel"), lower=True),
            "oneway": _normalize_text(tags.get("oneway"), lower=True),
            "surface": _normalize_text(tags.get("surface"), lower=True),
            "access": _normalize_text(tags.get("access"), lower=True),
        }
        return {key: value for key, value in properties.items() if value is not None}

    def _building_properties(self, *, element_type: str, element_id: Any, tags: dict[str, Any]) -> dict[str, Any]:
        properties = {
            "osm_type": element_type,
            "osm_id": element_id,
            "name": _normalize_text(tags.get("name")),
            "building": _normalize_text(tags.get("building"), lower=True),
            "building_levels": _normalize_text(tags.get("building:levels")),
            "height": _normalize_text(tags.get("height")),
            "amenity": _normalize_text(tags.get("amenity"), lower=True),
            "shop": _normalize_text(tags.get("shop"), lower=True),
            "office": _normalize_text(tags.get("office"), lower=True),
            "industrial": _normalize_text(tags.get("industrial"), lower=True),
            "landuse": _normalize_text(tags.get("landuse"), lower=True),
        }
        return {key: value for key, value in properties.items() if value is not None}

    def _waterway_properties(self, *, element_type: str, element_id: Any, tags: dict[str, Any]) -> dict[str, Any]:
        properties = {
            "osm_type": element_type,
            "osm_id": element_id,
            "name": _normalize_text(tags.get("name")),
            "waterway": _normalize_text(tags.get("waterway"), lower=True),
            "intermittent": _normalize_text(tags.get("intermittent"), lower=True),
            "tunnel": _normalize_text(tags.get("tunnel"), lower=True),
            "bridge": _normalize_text(tags.get("bridge"), lower=True),
            "natural": _normalize_text(tags.get("natural"), lower=True),
            "width": _normalize_text(tags.get("width")),
        }
        return {key: value for key, value in properties.items() if value is not None}

    def _administrative_properties(
        self,
        *,
        element_type: str,
        element_id: Any,
        tags: dict[str, Any],
    ) -> dict[str, Any]:
        properties = {
            "osm_type": element_type,
            "osm_id": element_id,
            "name": _normalize_text(tags.get("name")),
            "admin_level": _normalize_text(tags.get("admin_level")),
            "boundary": _normalize_text(tags.get("boundary"), lower=True),
            "place": _normalize_text(tags.get("place"), lower=True),
            "official_name": _normalize_text(tags.get("official_name")),
        }
        return {key: value for key, value in properties.items() if value is not None}

    def _normalize_element(
        self,
        *,
        element: dict[str, Any],
        feature_type: str,
    ) -> ContextFeatureCandidate | None:
        element_type = _normalize_text(element.get("type"), lower=True)
        provider_feature_id = _build_provider_feature_id(element_type, element.get("id"))
        if provider_feature_id is None or element_type is None:
            return None

        tags = element.get("tags")
        if not isinstance(tags, dict):
            tags = {}

        if element_type == "relation":
            raw_geometry = self._relation_to_geometry(
                feature_type=feature_type,
                tags=tags,
                raw_members=element.get("members"),
            )
        else:
            raw_geometry = self._way_to_geometry(
                feature_type=feature_type,
                tags=tags,
                raw_geometry=element.get("geometry"),
            )

        if raw_geometry is None:
            return None

        normalized_geometry = self._normalize_geometry(feature_type=feature_type, geometry=raw_geometry)
        if normalized_geometry is None:
            return None

        if feature_type == FEATURE_TYPE_ROAD:
            properties = self._road_properties(
                element_type=element_type,
                element_id=element.get("id"),
                tags=tags,
            )
            subtype = _normalize_text(tags.get("highway"), lower=True)
        elif feature_type == FEATURE_TYPE_BUILDING:
            properties = self._building_properties(
                element_type=element_type,
                element_id=element.get("id"),
                tags=tags,
            )
            subtype = _normalize_text(tags.get("building"), lower=True)
        elif feature_type == FEATURE_TYPE_WATERWAY:
            properties = self._waterway_properties(
                element_type=element_type,
                element_id=element.get("id"),
                tags=tags,
            )
            subtype = _normalize_text(tags.get("waterway"), lower=True) or _normalize_text(
                tags.get("natural"),
                lower=True,
            )
        else:
            properties = self._administrative_properties(
                element_type=element_type,
                element_id=element.get("id"),
                tags=tags,
            )
            subtype = _normalize_text(tags.get("place"), lower=True) or _normalize_text(tags.get("admin_level"))

        return ContextFeatureCandidate(
            provider_feature_id=provider_feature_id,
            feature_type=feature_type,
            feature_subtype=subtype,
            name=_normalize_text(tags.get("name")),
            geometry=_jsonable(mapping(normalized_geometry)),
            properties=properties,
            source_updated_at=_parse_timestamp(element.get("timestamp")),
        )

    def _fetch_by_type(
        self,
        *,
        intersects_geometry: dict[str, Any],
        feature_type: str,
        filter_templates: list[str],
        max_features: int,
    ) -> ContextFetchResult:
        poly_filter = _build_poly_filter(intersects_geometry)
        filters = [template.format(poly=poly_filter) for template in filter_templates]
        query = self._feature_query(filters=filters)
        elements = self._post_overpass_query(query, max_features=max_features)

        features: list[ContextFeatureCandidate] = []
        skipped_count = 0
        for element in elements:
            normalized = self._normalize_element(element=element, feature_type=feature_type)
            if normalized is None:
                skipped_count += 1
                continue
            features.append(normalized)

        logger.info(
            "Fetched OSM context feature_type=%s fetched=%s normalized=%s skipped=%s",
            feature_type,
            len(elements),
            len(features),
            skipped_count,
        )

        return ContextFetchResult(
            provider=self.provider_name,
            feature_type=feature_type,
            fetched_count=len(features),
            skipped_count=skipped_count,
            features=features,
        )

    def fetch_roads(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult:
        return self._fetch_by_type(
            intersects_geometry=intersects_geometry,
            feature_type=FEATURE_TYPE_ROAD,
            filter_templates=['way["highway"](poly:"{poly}")'],
            max_features=max_features,
        )

    def fetch_buildings(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult:
        return self._fetch_by_type(
            intersects_geometry=intersects_geometry,
            feature_type=FEATURE_TYPE_BUILDING,
            filter_templates=[
                'way["building"](poly:"{poly}")',
                'relation["building"](poly:"{poly}")',
            ],
            max_features=max_features,
        )

    def fetch_waterways(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult:
        return self._fetch_by_type(
            intersects_geometry=intersects_geometry,
            feature_type=FEATURE_TYPE_WATERWAY,
            filter_templates=[
                'way["waterway"](poly:"{poly}")',
                'relation["waterway"](poly:"{poly}")',
                'way["natural"="water"](poly:"{poly}")',
                'relation["natural"="water"](poly:"{poly}")',
            ],
            max_features=max_features,
        )

    def fetch_administrative_boundaries(
        self,
        *,
        intersects_geometry: dict[str, Any],
        max_features: int,
    ) -> ContextFetchResult:
        return self._fetch_by_type(
            intersects_geometry=intersects_geometry,
            feature_type=FEATURE_TYPE_ADMINISTRATIVE,
            filter_templates=[
                'relation["boundary"="administrative"](poly:"{poly}")',
                'way["boundary"="administrative"](poly:"{poly}")',
            ],
            max_features=max_features,
        )
