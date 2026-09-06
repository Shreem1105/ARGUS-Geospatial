from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from time import sleep
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.session import SessionLocal
from app.main import app
from app.models import Monitor

MONITOR_POLYGON = {
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

OVERLAP_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.845, 35.225],
            [-80.835, 35.225],
            [-80.835, 35.235],
            [-80.845, 35.235],
            [-80.845, 35.225],
        ]
    ],
}

OUTSIDE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-81.05, 35.40],
            [-81.04, 35.40],
            [-81.04, 35.41],
            [-81.05, 35.41],
            [-81.05, 35.40],
        ]
    ],
}

CONTAINED_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.848, 35.222],
            [-80.846, 35.222],
            [-80.846, 35.224],
            [-80.848, 35.224],
            [-80.848, 35.222],
        ]
    ],
}

SELF_INTERSECTING_POLYGON = {
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

OVERSIZED_POLYGON = {
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


def build_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Management Test Monitor",
        "description": "Monitor used for management and spatial tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)
    return payload


def parse_api_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> list[UUID]:
    monitor_ids: list[UUID] = []
    yield monitor_ids

    if not monitor_ids:
        return

    with SessionLocal() as db_session:
        db_session.execute(delete(Monitor).where(Monitor.id.in_(monitor_ids)))
        db_session.commit()


def create_monitor_and_track(
    client: TestClient,
    created_monitor_ids: list[UUID],
    **overrides: object,
) -> dict[str, object]:
    response = client.post("/monitors", json=build_create_payload(**overrides))
    assert response.status_code == 201

    body = response.json()
    created_monitor_ids.append(UUID(body["id"]))
    return body


def test_delete_monitor_existing_monitor_returns_204(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.delete(f"/monitors/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""


def test_delete_monitor_deleted_monitor_no_longer_retrievable(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(created["id"])

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    get_response = client.get(f"/monitors/{monitor_id}")
    assert get_response.status_code == 404

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count()).select_from(Monitor).where(Monitor.id == monitor_id)
        )

    assert count == 0


def test_delete_monitor_unknown_valid_uuid_returns_404(client: TestClient) -> None:
    response = client.delete(f"/monitors/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_delete_monitor_invalid_uuid_returns_422(client: TestClient) -> None:
    response = client.delete("/monitors/not-a-uuid")

    assert response.status_code == 422


def test_status_patch_active_to_paused(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"status": "paused"})

    assert response.status_code == 200
    assert response.json()["status"] == "paused"


def test_status_patch_paused_to_active(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = created["id"]

    pause_response = client.patch(f"/monitors/{monitor_id}", json={"status": "paused"})
    assert pause_response.status_code == 200

    activate_response = client.patch(f"/monitors/{monitor_id}", json={"status": "active"})

    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"


def test_status_patch_to_archived(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"status": "archived"})

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_status_patch_invalid_status_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"status": "invalid"})

    assert response.status_code == 422


def test_post_cannot_provide_status(client: TestClient) -> None:
    payload = build_create_payload(status="paused")

    response = client.post("/monitors", json=payload)

    assert response.status_code == 422


def test_status_update_changes_updated_at(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    original_updated_at = parse_api_datetime(created["updated_at"])

    sleep(0.02)
    response = client.patch(f"/monitors/{created['id']}", json={"status": "paused"})
    updated = response.json()

    assert response.status_code == 200
    assert parse_api_datetime(updated["updated_at"]) > original_updated_at


def test_status_update_preserves_created_at(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.patch(f"/monitors/{created['id']}", json={"status": "paused"})
    updated = response.json()

    assert response.status_code == 200
    assert updated["created_at"] == created["created_at"]


def test_list_status_filter_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    active = create_monitor_and_track(client, created_monitor_ids, name="active-monitor")
    paused = create_monitor_and_track(client, created_monitor_ids, name="paused-monitor")
    archived = create_monitor_and_track(client, created_monitor_ids, name="archived-monitor")

    client.patch(f"/monitors/{paused['id']}", json={"status": "paused"})
    client.patch(f"/monitors/{archived['id']}", json={"status": "archived"})

    active_response = client.get("/monitors?status=active")
    paused_response = client.get("/monitors?status=paused")
    archived_response = client.get("/monitors?status=archived")

    assert active_response.status_code == 200
    assert any(item["id"] == active["id"] for item in active_response.json())
    assert all(item["status"] == "active" for item in active_response.json())

    assert paused_response.status_code == 200
    assert any(item["id"] == paused["id"] for item in paused_response.json())
    assert all(item["status"] == "paused" for item in paused_response.json())

    assert archived_response.status_code == 200
    assert any(item["id"] == archived["id"] for item in archived_response.json())
    assert all(item["status"] == "archived" for item in archived_response.json())


def test_list_monitor_type_filter_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    general = create_monitor_and_track(client, created_monitor_ids, name="general-monitor")
    urban = create_monitor_and_track(client, created_monitor_ids, name="urban-monitor", monitor_type="urban")

    response = client.get("/monitors?monitor_type=urban")

    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == urban["id"] for item in body)
    assert all(item["monitor_type"] == "urban" for item in body)
    assert all(item["id"] != general["id"] for item in body)


def test_list_combined_filters_work(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    matching = create_monitor_and_track(
        client,
        created_monitor_ids,
        name="matching-monitor",
        monitor_type="general",
    )
    paused_general = create_monitor_and_track(
        client,
        created_monitor_ids,
        name="paused-general",
        monitor_type="general",
    )
    active_urban = create_monitor_and_track(
        client,
        created_monitor_ids,
        name="active-urban",
        monitor_type="urban",
    )

    client.patch(f"/monitors/{paused_general['id']}", json={"status": "paused"})

    response = client.get("/monitors?status=active&monitor_type=general")

    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == matching["id"] for item in body)
    assert all(item["status"] == "active" for item in body)
    assert all(item["monitor_type"] == "general" for item in body)
    assert all(item["id"] != paused_general["id"] for item in body)
    assert all(item["id"] != active_urban["id"] for item in body)


def test_list_pagination_works_with_filters(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    first = create_monitor_and_track(client, created_monitor_ids, name="page-filter-1")
    sleep(0.01)
    second = create_monitor_and_track(client, created_monitor_ids, name="page-filter-2")
    sleep(0.01)
    third = create_monitor_and_track(client, created_monitor_ids, name="page-filter-3")

    response = client.get("/monitors?status=active&monitor_type=general&limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == second["id"]
    assert body[0]["id"] != third["id"]
    assert body[0]["id"] != first["id"]


def test_list_invalid_status_query_returns_422(client: TestClient) -> None:
    response = client.get("/monitors?status=invalid")

    assert response.status_code == 422


def test_summary_endpoint_returns_200(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{created['id']}/summary")

    assert response.status_code == 200


def test_summary_geometry_type_is_polygon(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")

    assert response.status_code == 200
    assert response.json()["geometry_type"] == "Polygon"


def test_summary_srid_is_4326(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")

    assert response.status_code == 200
    assert response.json()["srid"] == 4326


def test_summary_area_m2_is_positive(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")

    assert response.status_code == 200
    assert response.json()["area_m2"] > 0


def test_summary_area_km2_matches_area_m2_conversion(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")
    body = response.json()

    assert response.status_code == 200
    assert body["area_km2"] == pytest.approx(body["area_m2"] / 1_000_000, rel=1e-9)


def test_summary_centroid_is_valid_geojson_point(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")
    centroid = response.json()["centroid"]

    assert response.status_code == 200
    assert centroid["type"] == "Point"
    assert len(centroid["coordinates"]) == 2


def test_summary_bounding_box_values_are_correct(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}/summary")
    bbox = response.json()["bounding_box"]

    assert response.status_code == 200
    assert bbox["min_lon"] == pytest.approx(-80.85)
    assert bbox["min_lat"] == pytest.approx(35.22)
    assert bbox["max_lon"] == pytest.approx(-80.84)
    assert bbox["max_lat"] == pytest.approx(35.23)


def test_summary_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.get(f"/monitors/{uuid4()}/summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_intersection_overlapping_polygon_returns_true(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)

    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OVERLAP_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersects"] is True


def test_intersection_overlap_area_is_positive(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OVERLAP_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersection_area_m2"] > 0


def test_intersection_overlap_percentage_is_positive(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OVERLAP_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersection_percentage_of_monitor"] > 0


def test_intersection_fully_outside_returns_false(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OUTSIDE_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersects"] is False


def test_intersection_non_overlap_area_is_zero(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OUTSIDE_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersection_area_m2"] == 0


def test_intersection_non_overlap_percentage_is_zero(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OUTSIDE_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersection_percentage_of_monitor"] == 0


def test_intersection_fully_contained_polygon_behaves_correctly(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(CONTAINED_POLYGON)},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["intersects"] is True
    assert body["intersection_area_m2"] > 0
    assert 0 < body["intersection_percentage_of_monitor"] < 100


def test_intersection_identical_polygon_is_approximately_100_percent(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(MONITOR_POLYGON)},
    )

    assert response.status_code == 200
    assert response.json()["intersection_percentage_of_monitor"] == pytest.approx(100.0, abs=0.2)


def test_intersection_invalid_self_intersecting_polygon_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(SELF_INTERSECTING_POLYGON)},
    )

    assert response.status_code == 422


def test_intersection_oversized_polygon_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(
        f"/monitors/{created['id']}/intersects",
        json={"geometry": deepcopy(OVERSIZED_POLYGON)},
    )

    assert response.status_code == 422


def test_intersection_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/monitors/{uuid4()}/intersects",
        json={"geometry": deepcopy(MONITOR_POLYGON)},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_regression_post_still_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids, name="regression-post")

    assert UUID(created["id"])


def test_regression_get_still_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get("/monitors")

    assert response.status_code == 200
    assert any(item["id"] == created["id"] for item in response.json())


def test_regression_patch_existing_fields_still_works(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.patch(
        f"/monitors/{created['id']}",
        json={"name": "Regression Updated Name"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Regression Updated Name"


def test_regression_geometry_serialization_is_geojson(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    response = client.get(f"/monitors/{created['id']}")
    geometry = response.json()["geometry"]

    assert response.status_code == 200
    assert geometry["type"] == "Polygon"
    assert isinstance(geometry["coordinates"], list)


def test_regression_health_and_ready_still_pass(client: TestClient) -> None:
    health_response = client.get("/health")
    ready_response = client.get("/ready")

    assert health_response.status_code == 200
    assert ready_response.status_code == 200
