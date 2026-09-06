from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.session import engine, get_db_session
from app.gis.conversion import geojson_polygon_to_wkb
from app.main import app
from app.models import Monitor

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


@pytest.fixture
def isolated_db_session() -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, autocommit=False, expire_on_commit=False)

    try:
        session.execute(delete(Monitor))
        session.flush()
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def isolated_client(isolated_db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db_session() -> Generator[Session, None, None]:
        yield isolated_db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def insert_monitor(
    db_session: Session,
    *,
    name: str,
    created_at: datetime | None = None,
) -> Monitor:
    monitor = Monitor(
        name=name,
        description="retrieval test monitor",
        geometry=geojson_polygon_to_wkb(deepcopy(VALID_CHARLOTTE_POLYGON)),
        monitor_type="general",
        sensitivity=0.5,
        minimum_change_area_m2=10.0,
        status="active",
    )

    if created_at is not None:
        monitor.created_at = created_at
        monitor.updated_at = created_at

    db_session.add(monitor)
    db_session.flush()
    db_session.refresh(monitor)
    return monitor


def test_get_monitors_empty_database_returns_empty_list(isolated_client: TestClient) -> None:
    response = isolated_client.get("/monitors")

    assert response.status_code == 200
    assert response.json() == []


def test_get_monitors_one_stored_monitor_is_returned(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    created = insert_monitor(isolated_db_session, name="single-monitor")

    response = isolated_client.get("/monitors")
    body = response.json()

    assert response.status_code == 200
    assert len(body) == 1
    assert body[0]["id"] == str(created.id)


def test_get_monitors_multiple_stored_monitors_are_returned(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    insert_monitor(isolated_db_session, name="monitor-a")
    insert_monitor(isolated_db_session, name="monitor-b")
    insert_monitor(isolated_db_session, name="monitor-c")

    response = isolated_client.get("/monitors")
    body = response.json()

    assert response.status_code == 200
    assert len(body) == 3


def test_get_monitors_geometry_is_geojson_polygon(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    insert_monitor(isolated_db_session, name="geometry-monitor")

    response = isolated_client.get("/monitors")
    geometry = response.json()[0]["geometry"]

    assert response.status_code == 200
    assert geometry["type"] == "Polygon"
    assert isinstance(geometry["coordinates"], list)


def test_get_monitors_newest_monitor_appears_first(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    base_time = datetime.now(UTC)
    oldest = insert_monitor(
        isolated_db_session,
        name="oldest",
        created_at=base_time,
    )
    middle = insert_monitor(
        isolated_db_session,
        name="middle",
        created_at=base_time + timedelta(seconds=1),
    )
    newest = insert_monitor(
        isolated_db_session,
        name="newest",
        created_at=base_time + timedelta(seconds=2),
    )

    response = isolated_client.get("/monitors")
    ids = [UUID(item["id"]) for item in response.json()]

    assert response.status_code == 200
    assert ids == [newest.id, middle.id, oldest.id]


def test_get_monitors_limit_parameter_works(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    base_time = datetime.now(UTC)
    insert_monitor(isolated_db_session, name="limit-a", created_at=base_time)
    second = insert_monitor(
        isolated_db_session,
        name="limit-b",
        created_at=base_time + timedelta(seconds=1),
    )
    third = insert_monitor(
        isolated_db_session,
        name="limit-c",
        created_at=base_time + timedelta(seconds=2),
    )

    response = isolated_client.get("/monitors?limit=2")
    ids = [UUID(item["id"]) for item in response.json()]

    assert response.status_code == 200
    assert len(ids) == 2
    assert ids == [third.id, second.id]


def test_get_monitors_offset_parameter_works(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    base_time = datetime.now(UTC)
    first = insert_monitor(isolated_db_session, name="offset-a", created_at=base_time)
    second = insert_monitor(
        isolated_db_session,
        name="offset-b",
        created_at=base_time + timedelta(seconds=1),
    )
    third = insert_monitor(
        isolated_db_session,
        name="offset-c",
        created_at=base_time + timedelta(seconds=2),
    )

    response = isolated_client.get("/monitors?limit=1&offset=1")
    ids = [UUID(item["id"]) for item in response.json()]

    assert response.status_code == 200
    assert ids == [second.id]
    assert ids != [third.id]
    assert ids != [first.id]


def test_get_monitors_limit_zero_returns_422(isolated_client: TestClient) -> None:
    response = isolated_client.get("/monitors?limit=0")

    assert response.status_code == 422


def test_get_monitors_limit_above_100_returns_422(isolated_client: TestClient) -> None:
    response = isolated_client.get("/monitors?limit=101")

    assert response.status_code == 422


def test_get_monitors_negative_offset_returns_422(isolated_client: TestClient) -> None:
    response = isolated_client.get("/monitors?offset=-1")

    assert response.status_code == 422


def test_get_monitor_by_id_existing_monitor_returns_200(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    monitor = insert_monitor(isolated_db_session, name="single-get")

    response = isolated_client.get(f"/monitors/{monitor.id}")

    assert response.status_code == 200


def test_get_monitor_by_id_returns_requested_id(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    monitor = insert_monitor(isolated_db_session, name="id-match")

    response = isolated_client.get(f"/monitors/{monitor.id}")
    body = response.json()

    assert response.status_code == 200
    assert body["id"] == str(monitor.id)


def test_get_monitor_by_id_geometry_returns_as_geojson(
    isolated_client: TestClient,
    isolated_db_session: Session,
) -> None:
    monitor = insert_monitor(isolated_db_session, name="geojson-get")

    response = isolated_client.get(f"/monitors/{monitor.id}")
    geometry = response.json()["geometry"]

    assert response.status_code == 200
    assert geometry["type"] == "Polygon"
    assert isinstance(geometry["coordinates"], list)


def test_get_monitor_by_id_unknown_valid_uuid_returns_404(
    isolated_client: TestClient,
) -> None:
    response = isolated_client.get(f"/monitors/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_get_monitor_by_id_invalid_uuid_returns_422(isolated_client: TestClient) -> None:
    response = isolated_client.get("/monitors/not-a-uuid")

    assert response.status_code == 422
