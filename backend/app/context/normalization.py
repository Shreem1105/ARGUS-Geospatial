from __future__ import annotations

ROAD_CLASS_MAP: dict[str, str] = {
    "motorway": "motorway",
    "motorway_link": "motorway",
    "trunk": "trunk",
    "trunk_link": "trunk",
    "primary": "primary",
    "primary_link": "primary",
    "secondary": "secondary",
    "secondary_link": "secondary",
    "tertiary": "tertiary",
    "tertiary_link": "tertiary",
    "residential": "residential",
    "living_street": "residential",
    "unclassified": "residential",
    "service": "service",
    "path": "path",
    "footway": "path",
    "cycleway": "path",
    "bridleway": "path",
    "track": "path",
    "steps": "path",
    "pedestrian": "path",
}


def normalize_road_class(highway: str | None) -> str:
    if highway is None:
        return "other"

    normalized = highway.strip().lower()
    if not normalized:
        return "other"

    return ROAD_CLASS_MAP.get(normalized, "other")

