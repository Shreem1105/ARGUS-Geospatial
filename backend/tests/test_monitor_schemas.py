from __future__ import annotations

import math
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.gis.validation import MAX_AOI_VERTEX_COUNT
from app.schemas.monitor import MonitorCreate, MonitorUpdate


VALID_CHARLOTTE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.85, 35.22],
            [-80.84, 35.22],
            [-80.84, 35.23],
            [-80.85, 35.23],
            [-80.85, 35.22],
        ]
    ],
}


def build_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Charlotte AOI",
        "description": None,
        "geometry": deepcopy(VALID_CHARLOTTE_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)
    return payload


def build_polygon_with_vertex_count(total_vertices: int) -> dict[str, object]:
    if total_vertices < 4:
        raise ValueError("total_vertices must be at least 4")

    unique_vertices = total_vertices - 1
    radius = 0.01
    ring: list[list[float]] = []

    for index in range(unique_vertices):
        angle = (2 * math.pi * index) / unique_vertices
        ring.append(
            [
                -80.85 + (radius * math.cos(angle)),
                35.22 + (radius * math.sin(angle)),
            ]
        )

    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def test_monitor_create_valid_charlotte_polygon() -> None:
    payload = build_create_payload()
    model = MonitorCreate(**payload)

    assert model.name == "Charlotte AOI"
    assert model.geometry.type == "Polygon"


def test_monitor_create_valid_with_description() -> None:
    payload = build_create_payload(description="  Monitoring area for city expansion  ")
    model = MonitorCreate(**payload)

    assert model.description == "Monitoring area for city expansion"


@pytest.mark.parametrize("sensitivity", [0.0, 1.0])
def test_monitor_create_sensitivity_boundaries_are_valid(sensitivity: float) -> None:
    payload = build_create_payload(sensitivity=sensitivity)
    model = MonitorCreate(**payload)

    assert model.sensitivity == sensitivity


def test_monitor_create_zero_minimum_change_area_is_valid() -> None:
    payload = build_create_payload(minimum_change_area_m2=0)
    model = MonitorCreate(**payload)

    assert model.minimum_change_area_m2 == 0


def test_monitor_create_rejects_point_geometry() -> None:
    payload = build_create_payload(geometry={"type": "Point", "coordinates": [-80.85, 35.22]})

    with pytest.raises(ValidationError, match="geometry.type must be 'Polygon'"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_linestring_geometry() -> None:
    payload = build_create_payload(
        geometry={
            "type": "LineString",
            "coordinates": [[-80.85, 35.22], [-80.84, 35.23]],
        }
    )

    with pytest.raises(ValidationError, match="geometry.type must be 'Polygon'"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_latitude_out_of_range() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-80.85, 95.0],
                    [-80.84, 35.22],
                    [-80.84, 35.23],
                    [-80.85, 35.23],
                    [-80.85, 95.0],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="latitude must be between -90 and 90"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_longitude_out_of_range() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-181.0, 35.22],
                    [-80.84, 35.22],
                    [-80.84, 35.23],
                    [-181.0, 35.23],
                    [-181.0, 35.22],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="longitude must be between -180 and 180"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_unclosed_polygon() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-80.85, 35.22],
                    [-80.84, 35.22],
                    [-80.84, 35.23],
                    [-80.85, 35.23],
                    [-80.84, 35.24],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="must be closed"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_too_few_coordinates() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-80.85, 35.22],
                    [-80.84, 35.22],
                    [-80.85, 35.22],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="at least 4 positions"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_self_intersecting_polygon() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-80.85, 35.22],
                    [-80.84, 35.23],
                    [-80.84, 35.22],
                    [-80.85, 35.23],
                    [-80.85, 35.22],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="valid Polygon"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_zero_area_polygon() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-80.85, 35.22],
                    [-80.84, 35.22],
                    [-80.83, 35.22],
                    [-80.85, 35.22],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="valid Polygon|area must be greater than zero"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_vertex_count_over_limit() -> None:
    payload = build_create_payload(
        geometry=build_polygon_with_vertex_count(MAX_AOI_VERTEX_COUNT + 1)
    )

    with pytest.raises(ValidationError, match="maximum vertex count"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_polygon_larger_than_max_area_limit() -> None:
    payload = build_create_payload(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [-82.0, 34.0],
                    [-78.0, 34.0],
                    [-78.0, 36.0],
                    [-82.0, 36.0],
                    [-82.0, 34.0],
                ]
            ],
        }
    )

    with pytest.raises(ValidationError, match="maximum allowed area"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_sensitivity_below_zero() -> None:
    payload = build_create_payload(sensitivity=-0.01)

    with pytest.raises(ValidationError):
        MonitorCreate(**payload)


def test_monitor_create_rejects_sensitivity_above_one() -> None:
    payload = build_create_payload(sensitivity=1.01)

    with pytest.raises(ValidationError):
        MonitorCreate(**payload)


def test_monitor_create_rejects_negative_minimum_change_area() -> None:
    payload = build_create_payload(minimum_change_area_m2=-1)

    with pytest.raises(ValidationError):
        MonitorCreate(**payload)


def test_monitor_create_rejects_blank_name() -> None:
    payload = build_create_payload(name="   ")

    with pytest.raises(ValidationError, match="name must not be blank"):
        MonitorCreate(**payload)


def test_monitor_create_rejects_blank_monitor_type() -> None:
    payload = build_create_payload(monitor_type="   ")

    with pytest.raises(ValidationError, match="monitor_type must not be blank"):
        MonitorCreate(**payload)


def test_monitor_update_valid_partial_geometry() -> None:
    model = MonitorUpdate(geometry=deepcopy(VALID_CHARLOTTE_POLYGON))

    assert model.geometry is not None
    assert model.geometry.type == "Polygon"


def test_monitor_update_rejects_invalid_geometry_type() -> None:
    with pytest.raises(ValidationError, match="geometry.type must be 'Polygon'"):
        MonitorUpdate(geometry={"type": "Point", "coordinates": [-80.85, 35.22]})

