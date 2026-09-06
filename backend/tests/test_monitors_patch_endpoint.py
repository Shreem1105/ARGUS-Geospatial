from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from time import sleep
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db.session import SessionLocal
from app.main import app
from app.models import Monitor

VALID_CREATE_POLYGON = {
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

VALID_PATCH_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.86, 35.24],
            [-80.85, 35.24],
            [-80.85, 35.25],
            [-80.86, 35.25],
            [-80.86, 35.24],
        ]
    ],
}


def build_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Patch Test Monitor",
        "description": "Monitor used for PATCH endpoint tests",
        "geometry": deepcopy(VALID_CREATE_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> list[UUID]:
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
    created_monitor_ids.append(UUID(body["id"]))
    return body


def parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_patch_monitor_update_name_only(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"name": "Updated AOI"})
    body = response.json()

    assert response.status_code == 200
    assert body["name"] == "Updated AOI"


def test_patch_monitor_update_sensitivity_only(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"sensitivity": 0.8})
    body = response.json()

    assert response.status_code == 200
    assert body["sensitivity"] == 0.8


def test_patch_monitor_update_multiple_fields(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={
            "name": "Charlotte Expansion",
            "sensitivity": 0.7,
            "minimum_change_area_m2": 250,
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["name"] == "Charlotte Expansion"
    assert body["sensitivity"] == 0.7
    assert body["minimum_change_area_m2"] == 250.0


def test_patch_monitor_update_geometry_successfully(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={"geometry": deepcopy(VALID_PATCH_POLYGON)},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["geometry"] == VALID_PATCH_POLYGON


def test_patch_monitor_geometry_response_is_geojson_polygon(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={"geometry": deepcopy(VALID_PATCH_POLYGON)},
    )
    geometry = response.json()["geometry"]

    assert response.status_code == 200
    assert geometry["type"] == "Polygon"
    assert isinstance(geometry["coordinates"], list)


def test_patch_monitor_updated_geometry_stored_with_srid_4326(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(created["id"])

    patch_response = client.patch(
        f"/monitors/{monitor_id}",
        json={"geometry": deepcopy(VALID_PATCH_POLYGON)},
    )
    assert patch_response.status_code == 200

    with SessionLocal() as db_session:
        srid = db_session.execute(
            text("SELECT ST_SRID(geometry) FROM monitors WHERE id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert srid == 4326


def test_patch_monitor_updated_geometry_is_valid_in_postgis(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(created["id"])

    patch_response = client.patch(
        f"/monitors/{monitor_id}",
        json={"geometry": deepcopy(VALID_PATCH_POLYGON)},
    )
    assert patch_response.status_code == 200

    with SessionLocal() as db_session:
        row = db_session.execute(
            text(
                "SELECT ST_IsValid(geometry) AS is_valid, ST_Area(geometry::geography) AS area_m2 FROM monitors WHERE id = :monitor_id"
            ),
            {"monitor_id": monitor_id},
        ).mappings().one()

    assert row["is_valid"] is True
    assert row["area_m2"] > 0


def test_patch_monitor_clear_description_with_null(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"description": None})
    body = response.json()

    assert response.status_code == 200
    assert body["description"] is None


def test_patch_monitor_unspecified_fields_remain_unchanged(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"name": "Renamed Monitor"})
    body = response.json()

    assert response.status_code == 200
    assert body["name"] == "Renamed Monitor"
    assert body["sensitivity"] == created["sensitivity"]
    assert body["minimum_change_area_m2"] == created["minimum_change_area_m2"]
    assert body["monitor_type"] == created["monitor_type"]
    assert body["description"] == created["description"]


def test_patch_monitor_updated_at_increases_after_successful_update(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    original_updated_at = parse_api_datetime(created["updated_at"])

    sleep(0.02)
    response = client.patch(f"/monitors/{created['id']}", json={"name": "Updated Timestamp"})
    body = response.json()
    new_updated_at = parse_api_datetime(body["updated_at"])

    assert response.status_code == 200
    assert new_updated_at > original_updated_at


def test_patch_monitor_created_at_remains_unchanged(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    original_created_at = created["created_at"]

    response = client.patch(f"/monitors/{created['id']}", json={"sensitivity": 0.65})
    body = response.json()

    assert response.status_code == 200
    assert body["created_at"] == original_created_at


def test_patch_monitor_invalid_sensitivity_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"sensitivity": 1.5})

    assert response.status_code == 422


def test_patch_monitor_negative_minimum_change_area_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={"minimum_change_area_m2": -10},
    )

    assert response.status_code == 422


def test_patch_monitor_invalid_geometry_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={
            "geometry": {
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
        },
    )

    assert response.status_code == 422


def test_patch_monitor_oversized_aoi_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(
        f"/monitors/{created['id']}",
        json={
            "geometry": {
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
        },
    )

    assert response.status_code == 422


def test_patch_monitor_empty_payload_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={})

    assert response.status_code == 422
    assert "at least one field" in str(response.json())


def test_patch_monitor_unknown_valid_uuid_returns_404(client: TestClient) -> None:
    response = client.patch(f"/monitors/{uuid4()}", json={"name": "Unknown"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_patch_monitor_invalid_uuid_returns_422(client: TestClient) -> None:
    response = client.patch("/monitors/not-a-uuid", json={"name": "Invalid UUID"})

    assert response.status_code == 422


def test_patch_monitor_invalid_status_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"status": "invalid"})

    assert response.status_code == 422


def test_patch_monitor_existing_get_endpoints_return_updated_values(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = created["id"]

    patch_response = client.patch(
        f"/monitors/{monitor_id}",
        json={"name": "GET Reflected Name", "sensitivity": 0.77},
    )
    assert patch_response.status_code == 200

    get_one_response = client.get(f"/monitors/{monitor_id}")
    get_one_body = get_one_response.json()
    assert get_one_response.status_code == 200
    assert get_one_body["name"] == "GET Reflected Name"
    assert get_one_body["sensitivity"] == 0.77

    list_response = client.get("/monitors")
    assert list_response.status_code == 200
    list_item = next(item for item in list_response.json() if item["id"] == monitor_id)
    assert list_item["name"] == "GET Reflected Name"
    assert list_item["sensitivity"] == 0.77


def test_patch_monitor_existing_post_behavior_still_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    response = client.post("/monitors", json=build_create_payload(name="POST still works"))
    body = response.json()

    assert response.status_code == 201
    assert UUID(body["id"])
    created_monitor_ids.append(UUID(body["id"]))
