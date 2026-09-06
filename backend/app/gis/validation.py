from __future__ import annotations

from typing import Any

from pyproj import Geod
from shapely.geometry import Polygon

MIN_LINEAR_RING_COORDINATES = 4
MAX_AOI_VERTEX_COUNT = 5000
MAX_AOI_AREA_KM2 = 10000.0

WGS84_GEOD = Geod(ellps="WGS84")


def _is_numeric_coordinate(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_and_normalize_ring(ring: Any, ring_index: int) -> list[tuple[float, float]]:
    if not isinstance(ring, list):
        raise ValueError(f"ring {ring_index} must be a list of [longitude, latitude] positions")

    if len(ring) < MIN_LINEAR_RING_COORDINATES:
        raise ValueError(
            f"ring {ring_index} must contain at least {MIN_LINEAR_RING_COORDINATES} positions including closure"
        )

    normalized_ring: list[tuple[float, float]] = []
    for position_index, position in enumerate(ring):
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            raise ValueError(
                f"ring {ring_index} position {position_index} must be [longitude, latitude]"
            )

        longitude, latitude = position
        if not _is_numeric_coordinate(longitude) or not _is_numeric_coordinate(latitude):
            raise ValueError(
                f"ring {ring_index} position {position_index} must contain numeric longitude/latitude values"
            )

        longitude_float = float(longitude)
        latitude_float = float(latitude)

        if not -180 <= longitude_float <= 180:
            raise ValueError(
                f"ring {ring_index} position {position_index} longitude must be between -180 and 180"
            )

        if not -90 <= latitude_float <= 90:
            raise ValueError(
                f"ring {ring_index} position {position_index} latitude must be between -90 and 90"
            )

        normalized_ring.append((longitude_float, latitude_float))

    if normalized_ring[0] != normalized_ring[-1]:
        raise ValueError(
            f"ring {ring_index} must be closed (first and last coordinates must match exactly)"
        )

    return normalized_ring


def calculate_polygon_area_km2(polygon: Polygon) -> float:
    area_m2, _ = WGS84_GEOD.geometry_area_perimeter(polygon)
    return abs(area_m2) / 1_000_000


def validate_geojson_polygon(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("geometry must be a GeoJSON object")

    geometry_type = value.get("type")
    if geometry_type != "Polygon":
        raise ValueError("geometry.type must be 'Polygon'")

    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("geometry.coordinates must be a non-empty list of linear rings")

    normalized_rings = [
        _validate_and_normalize_ring(ring, ring_index)
        for ring_index, ring in enumerate(coordinates)
    ]

    total_vertices = sum(len(ring) for ring in normalized_rings)
    if total_vertices > MAX_AOI_VERTEX_COUNT:
        raise ValueError(
            f"polygon exceeds maximum vertex count of {MAX_AOI_VERTEX_COUNT}"
        )

    polygon = Polygon(shell=normalized_rings[0], holes=normalized_rings[1:] or None)

    if polygon.is_empty:
        raise ValueError("geometry must not be empty")

    if not polygon.is_valid:
        raise ValueError("geometry must be a valid Polygon")

    area_km2 = calculate_polygon_area_km2(polygon)
    if area_km2 <= 0:
        raise ValueError("geometry area must be greater than zero")

    if area_km2 > MAX_AOI_AREA_KM2:
        raise ValueError(
            f"geometry area exceeds maximum allowed area of {MAX_AOI_AREA_KM2} km^2"
        )

    return {
        "type": "Polygon",
        "coordinates": [
            [[longitude, latitude] for longitude, latitude in ring]
            for ring in normalized_rings
        ],
    }

