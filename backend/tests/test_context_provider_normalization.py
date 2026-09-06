from __future__ import annotations

from shapely.geometry import MultiLineString, MultiPolygon, Polygon

from app.context import (
    FEATURE_TYPE_ADMINISTRATIVE,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_WATERWAY,
)
from app.context.normalization import normalize_road_class
from app.context.osm import OpenStreetMapProvider


def _way_coords() -> list[dict[str, float]]:
    return [
        {"lon": -80.851, "lat": 35.222},
        {"lon": -80.850, "lat": 35.223},
        {"lon": -80.849, "lat": 35.224},
    ]


def _polygon_ring() -> list[dict[str, float]]:
    return [
        {"lon": -80.8510, "lat": 35.2220},
        {"lon": -80.8505, "lat": 35.2220},
        {"lon": -80.8505, "lat": 35.2225},
        {"lon": -80.8510, "lat": 35.2225},
        {"lon": -80.8510, "lat": 35.2220},
    ]


def test_normalize_road_class_mapping_values() -> None:
    assert normalize_road_class("motorway") == "motorway"
    assert normalize_road_class("trunk_link") == "trunk"
    assert normalize_road_class("primary") == "primary"
    assert normalize_road_class("secondary_link") == "secondary"
    assert normalize_road_class("tertiary") == "tertiary"
    assert normalize_road_class("residential") == "residential"
    assert normalize_road_class("service") == "service"
    assert normalize_road_class("footway") == "path"
    assert normalize_road_class("unknown-custom") == "other"
    assert normalize_road_class(None) == "other"


def test_osm_road_normalization_retains_expected_fields() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 1001,
        "timestamp": "2026-09-01T10:11:12Z",
        "geometry": _way_coords(),
        "tags": {
            "name": "Tryon Street",
            "highway": "primary",
            "lanes": "2",
            "maxspeed": "35 mph",
            "bridge": "no",
            "tunnel": "no",
            "oneway": "yes",
            "surface": "asphalt",
            "access": "yes",
        },
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_ROAD)

    assert normalized is not None
    assert normalized.provider_feature_id == "way/1001"
    assert normalized.feature_subtype == "primary"
    assert normalized.properties["highway"] == "primary"
    assert normalized.properties["road_class"] == "primary"
    assert normalized.properties["lanes"] == "2"
    assert normalized.properties["oneway"] == "yes"


def test_osm_building_normalization_retains_expected_fields() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 2001,
        "timestamp": "2026-09-01T10:11:12Z",
        "geometry": _polygon_ring(),
        "tags": {
            "name": "City Hall Annex",
            "building": "yes",
            "building:levels": "4",
            "height": "19",
            "amenity": "public_building",
            "shop": "no",
            "office": "government",
            "industrial": "no",
            "landuse": "civic_admin",
        },
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_BUILDING)

    assert normalized is not None
    assert normalized.provider_feature_id == "way/2001"
    assert normalized.feature_subtype == "yes"
    assert normalized.properties["building"] == "yes"
    assert normalized.properties["building_levels"] == "4"
    assert normalized.properties["office"] == "government"


def test_osm_waterway_normalization_retains_expected_fields() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 3001,
        "geometry": _way_coords(),
        "tags": {
            "name": "Little Sugar Creek",
            "waterway": "stream",
            "intermittent": "no",
            "tunnel": "no",
            "bridge": "no",
            "width": "4",
        },
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_WATERWAY)

    assert normalized is not None
    assert normalized.provider_feature_id == "way/3001"
    assert normalized.feature_subtype == "stream"
    assert normalized.properties["waterway"] == "stream"
    assert normalized.properties["width"] == "4"


def test_osm_administrative_normalization_retains_expected_fields() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 4001,
        "geometry": _polygon_ring(),
        "tags": {
            "name": "Charlotte",
            "admin_level": "8",
            "boundary": "administrative",
            "place": "city",
            "official_name": "City of Charlotte",
        },
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_ADMINISTRATIVE)

    assert normalized is not None
    assert normalized.provider_feature_id == "way/4001"
    assert normalized.feature_subtype == "city"
    assert normalized.properties["admin_level"] == "8"
    assert normalized.properties["boundary"] == "administrative"


def test_absent_name_remains_none() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 5001,
        "geometry": _way_coords(),
        "tags": {"highway": "service"},
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_ROAD)

    assert normalized is not None
    assert normalized.name is None


def test_malformed_geometry_is_skipped() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "way",
        "id": 6001,
        "geometry": [{"lon": -80.851, "lat": 35.222}],
        "tags": {"highway": "residential"},
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_ROAD)
    assert normalized is None


def test_multilinestring_supported_for_roads() -> None:
    provider = OpenStreetMapProvider()
    geometry = MultiLineString(
        [
            [(-80.851, 35.222), (-80.850, 35.223)],
            [(-80.850, 35.223), (-80.849, 35.224)],
        ]
    )

    normalized = provider._normalize_geometry(feature_type=FEATURE_TYPE_ROAD, geometry=geometry)

    assert normalized is not None
    assert normalized.geom_type == "MultiLineString"


def test_multipolygon_supported_for_buildings() -> None:
    provider = OpenStreetMapProvider()
    polygon_one = Polygon(
        [
            (-80.8510, 35.2220),
            (-80.8507, 35.2220),
            (-80.8507, 35.2223),
            (-80.8510, 35.2223),
            (-80.8510, 35.2220),
        ]
    )
    polygon_two = Polygon(
        [
            (-80.8506, 35.2220),
            (-80.8503, 35.2220),
            (-80.8503, 35.2223),
            (-80.8506, 35.2223),
            (-80.8506, 35.2220),
        ]
    )
    geometry = MultiPolygon([polygon_one, polygon_two])

    normalized = provider._normalize_geometry(feature_type=FEATURE_TYPE_BUILDING, geometry=geometry)

    assert normalized is not None
    assert normalized.geom_type == "MultiPolygon"


def test_relation_areal_polygonization_supported() -> None:
    provider = OpenStreetMapProvider()
    element = {
        "type": "relation",
        "id": 7001,
        "tags": {"boundary": "administrative", "admin_level": "6", "name": "Mecklenburg County"},
        "members": [
            {
                "type": "way",
                "ref": 701,
                "geometry": [
                    {"lon": -80.8520, "lat": 35.2210},
                    {"lon": -80.8480, "lat": 35.2210},
                    {"lon": -80.8480, "lat": 35.2250},
                    {"lon": -80.8520, "lat": 35.2250},
                    {"lon": -80.8520, "lat": 35.2210},
                ],
            }
        ],
    }

    normalized = provider._normalize_element(element=element, feature_type=FEATURE_TYPE_ADMINISTRATIVE)

    assert normalized is not None
    assert normalized.provider_feature_id == "relation/7001"
    assert normalized.geometry["type"] in {"Polygon", "MultiPolygon"}
