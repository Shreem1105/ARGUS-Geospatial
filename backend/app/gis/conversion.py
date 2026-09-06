from __future__ import annotations

from typing import Any

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, mapping, shape

WGS84_SRID = 4326


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, list):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable_value(item) for key, item in value.items()}
    return value


def geojson_geometry_to_wkb(geometry: dict[str, Any]) -> WKBElement:
    shapely_geometry = shape(geometry)
    return from_shape(shapely_geometry, srid=WGS84_SRID)


def wkb_to_geojson_geometry(geometry: WKBElement) -> dict[str, Any]:
    shapely_geometry = to_shape(geometry)
    return _jsonable_value(mapping(shapely_geometry))


def geojson_polygon_to_wkb(geometry: dict[str, Any]) -> WKBElement:
    coordinates = geometry["coordinates"]
    shell = coordinates[0]
    holes = coordinates[1:] or None
    polygon = Polygon(shell=shell, holes=holes)
    return from_shape(polygon, srid=WGS84_SRID)


def wkb_to_geojson_polygon(geometry: WKBElement) -> dict[str, Any]:
    polygon = to_shape(geometry)
    if not isinstance(polygon, Polygon):
        raise ValueError("database geometry is not a Polygon")

    coordinates: list[list[list[float]]] = [
        [[float(longitude), float(latitude)] for longitude, latitude in polygon.exterior.coords]
    ]
    coordinates.extend(
        [
            [[float(longitude), float(latitude)] for longitude, latitude in ring.coords]
            for ring in polygon.interiors
        ]
    )

    return {"type": "Polygon", "coordinates": coordinates}
