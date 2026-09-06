from __future__ import annotations

import math
from collections.abc import Generator
from copy import deepcopy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from app.gis.validation import MAX_AOI_VERTEX_COUNT
from app.main import app
from app.models import Monitor
from app.db.session import SessionLocal

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
        "name": "Charlotte Endpoint AOI",
        "description": "API integration test",
        "geometry": deepcopy(VALID_CHARLOTTE_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 10.0,
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


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> Generator[list[UUID], None, None]:
    created_ids: list[UUID] = []
    yield created_ids

    if not created_ids:
        return

    with SessionLocal() as db_session:
        db_session.execute(delete(Monitor).where(Monitor.id.in_(created_ids)))
        db_session.commit()


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID]) -> dict[str, object]:
    response = client.post("/monitors", json=build_create_payload())
    assert response.status_code == 201

    body = response.json()
    monitor_id = UUID(body["id"])
    created_monitor_ids.append(monitor_id)
    return body


def test_post_monitors_valid_payload_returns_201(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    response = client.post("/monitors", json=build_create_payload())

    assert response.status_code == 201
    created_monitor_ids.append(UUID(response.json()["id"]))


def test_post_monitors_response_contains_uuid(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    body = create_monitor_and_track(client, created_monitor_ids)
    assert UUID(body["id"])


def test_post_monitors_response_geometry_is_geojson_polygon(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    body = create_monitor_and_track(client, created_monitor_ids)

    assert body["geometry"]["type"] == "Polygon"
    assert isinstance(body["geometry"]["coordinates"], list)


def test_post_monitors_response_status_is_active(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    body = create_monitor_and_track(client, created_monitor_ids)
    assert body["status"] == "active"


def test_post_monitors_response_last_analyzed_at_is_null(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    body = create_monitor_and_track(client, created_monitor_ids)
    assert body["last_analyzed_at"] is None


def test_post_monitors_stored_geometry_uses_srid_4326(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    body = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(body["id"])

    with SessionLocal() as db_session:
        srid = db_session.execute(
            text("SELECT ST_SRID(geometry) FROM monitors WHERE id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert srid == 4326


def test_post_monitors_invalid_polygon_returns_422(client: TestClient) -> None:
    payload = build_create_payload(
        geometry={"type": "Point", "coordinates": [-80.85, 35.22]}
    )
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_self_intersecting_polygon_returns_422(client: TestClient) -> None:
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
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_oversized_aoi_returns_422(client: TestClient) -> None:
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
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_invalid_sensitivity_returns_422(client: TestClient) -> None:
    payload = build_create_payload(sensitivity=1.5)
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_negative_minimum_change_area_returns_422(client: TestClient) -> None:
    payload = build_create_payload(minimum_change_area_m2=-5)
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_extra_server_managed_field_returns_422(client: TestClient) -> None:
    payload = build_create_payload(status="paused")
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_post_monitors_successful_request_inserts_row(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    with SessionLocal() as db_session:
        before_count = db_session.scalar(select(func.count()).select_from(Monitor))

    response = client.post("/monitors", json=build_create_payload())
    assert response.status_code == 201
    created_monitor_ids.append(UUID(response.json()["id"]))

    with SessionLocal() as db_session:
        after_count = db_session.scalar(select(func.count()).select_from(Monitor))

    assert after_count == before_count + 1


def test_post_monitors_test_cleanup_removes_inserted_rows(client: TestClient) -> None:
    created_id: UUID | None = None

    try:
        response = client.post("/monitors", json=build_create_payload())
        assert response.status_code == 201

        created_id = UUID(response.json()["id"])

        with SessionLocal() as db_session:
            inserted_count = db_session.scalar(
                select(func.count()).select_from(Monitor).where(Monitor.id == created_id)
            )
            assert inserted_count == 1

            db_session.execute(delete(Monitor).where(Monitor.id == created_id))
            db_session.commit()

            remaining_count = db_session.scalar(
                select(func.count()).select_from(Monitor).where(Monitor.id == created_id)
            )

        assert remaining_count == 0
    finally:
        if created_id is not None:
            with SessionLocal() as db_session:
                db_session.execute(delete(Monitor).where(Monitor.id == created_id))
                db_session.commit()


def test_post_monitors_vertex_limit_validation_still_applies(client: TestClient) -> None:
    payload = build_create_payload(
        geometry=build_polygon_with_vertex_count(MAX_AOI_VERTEX_COUNT + 1)
    )
    response = client.post("/monitors", json=payload)

    assert response.status_code == 422
