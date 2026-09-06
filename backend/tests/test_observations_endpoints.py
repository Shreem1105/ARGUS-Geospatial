from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import Monitor, SatelliteObservation
from app.satellite import SatelliteProviderError, SatelliteSearchResult, get_satellite_provider

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

OBSERVATION_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.849, 35.221],
            [-80.839, 35.221],
            [-80.839, 35.231],
            [-80.849, 35.231],
            [-80.849, 35.221],
        ]
    ],
}

OVERLAP_GEOMETRY = {
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


class FakeSatelliteProvider:
    provider_name = "planetary_computer"

    def __init__(
        self,
        observations: list[dict[str, object]] | None = None,
        *,
        collection: str = "sentinel-2-l2a",
        skipped_count: int = 0,
        raise_error: bool = False,
    ) -> None:
        self.collection = collection
        self._observations = observations or []
        self._skipped_count = skipped_count
        self._raise_error = raise_error
        self.last_call: dict[str, object] | None = None

    def search_sentinel2_observations(
        self,
        *,
        intersects_geometry: dict[str, object],
        start_datetime: datetime,
        end_datetime: datetime,
        max_cloud_cover: float | None,
        limit: int,
    ) -> SatelliteSearchResult:
        self.last_call = {
            "intersects_geometry": intersects_geometry,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "max_cloud_cover": max_cloud_cover,
            "limit": limit,
        }

        if self._raise_error:
            raise SatelliteProviderError("provider unavailable")

        return SatelliteSearchResult(
            provider=self.provider_name,
            collection=self.collection,
            observations=deepcopy(self._observations),
            skipped_count=self._skipped_count,
        )


@pytest.fixture(autouse=True)
def clear_provider_override() -> None:
    yield
    app.dependency_overrides.pop(get_satellite_provider, None)


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


def build_monitor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Observation Test Monitor",
        "description": "Monitor for observation endpoint tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)
    return payload


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> dict[str, object]:
    response = client.post("/monitors", json=build_monitor_payload(**overrides))
    assert response.status_code == 201
    body = response.json()
    created_monitor_ids.append(UUID(body["id"]))
    return body


def build_provider_observation(
    *,
    item_id: str,
    acquired_at: str,
    cloud_cover: float | None = 10.0,
    platform: str = "sentinel-2b",
    sensor: str = "MSI",
    geometry: dict[str, object] | None = None,
    assets: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "provider": "planetary_computer",
        "collection": "sentinel-2-l2a",
        "item_id": item_id,
        "platform": platform,
        "sensor": sensor,
        "acquired_at": acquired_at,
        "cloud_cover": cloud_cover,
        "geometry": deepcopy(geometry or OBSERVATION_GEOMETRY),
        "bbox": [-80.849, 35.221, -80.839, 35.231],
        "thumbnail_url": "https://example.com/thumbnail.jpg",
        "assets": assets
        or {
            "B04": {
                "href": "https://example.com/B04.tif",
                "media_type": "image/tiff; application=geotiff",
                "roles": ["data"],
                "title": "Band 4",
            },
            "visual": {
                "href": "https://example.com/visual.tif",
                "media_type": "image/tiff; application=geotiff",
                "roles": ["visual"],
                "title": "Visual",
            },
        },
        "metadata": {
            "constellation": "sentinel-2",
            "proj:epsg": 32617,
            "gsd": 10,
        },
    }


def set_provider(provider: FakeSatelliteProvider) -> None:
    app.dependency_overrides[get_satellite_provider] = lambda: provider


def search_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_date": "2026-08-01",
        "end_date": "2026-09-01",
        "max_cloud_cover": 40,
        "limit": 20,
    }
    payload.update(overrides)
    return payload


def run_search(client: TestClient, monitor_id: str, **overrides: object):
    return client.post(f"/monitors/{monitor_id}/observations/search", json=search_payload(**overrides))


def test_observation_persists_from_search(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_OBS_PERSIST_1", acquired_at="2026-08-15T10:00:00Z")
        ]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"])

    assert response.status_code == 200
    assert response.json()["count"] == 1

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count())
            .select_from(SatelliteObservation)
            .where(SatelliteObservation.monitor_id == monitor_id)
        )
    assert count == 1


def test_observation_monitor_fk_enforced(client: TestClient) -> None:
    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=uuid4(),
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id="S2A_FK_FAIL_1",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            cloud_cover=10,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            assets={"B04": {"href": "https://example.com/B04.tif"}},
            metadata_={"constellation": "sentinel-2"},
        )

        with pytest.raises(IntegrityError):
            db_session.add(observation)
            db_session.commit()
        db_session.rollback()


def test_observation_duplicate_unique_constraint_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    with SessionLocal() as db_session:
        first = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id="S2A_UNIQUE_1",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            cloud_cover=10,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            assets={"B04": {"href": "https://example.com/B04.tif"}},
            metadata_={"constellation": "sentinel-2"},
        )
        db_session.add(first)
        db_session.commit()

        duplicate = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id="S2A_UNIQUE_1",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            cloud_cover=20,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            assets={"B08": {"href": "https://example.com/B08.tif"}},
            metadata_={"constellation": "sentinel-2"},
        )

        with pytest.raises(IntegrityError):
            db_session.add(duplicate)
            db_session.commit()
        db_session.rollback()


def test_observation_cloud_cover_below_zero_rejected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id="S2A_CC_NEGATIVE",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            cloud_cover=-1,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            assets={"B04": {"href": "https://example.com/B04.tif"}},
            metadata_={"constellation": "sentinel-2"},
        )

        with pytest.raises(IntegrityError):
            db_session.add(observation)
            db_session.commit()
        db_session.rollback()


def test_observation_cloud_cover_above_hundred_rejected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id="S2A_CC_TOO_HIGH",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            cloud_cover=101,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            assets={"B04": {"href": "https://example.com/B04.tif"}},
            metadata_={"constellation": "sentinel-2"},
        )

        with pytest.raises(IntegrityError):
            db_session.add(observation)
            db_session.commit()
        db_session.rollback()


def test_observation_geometry_srid_is_4326(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_SRID_1", acquired_at="2026-08-15T10:00:00Z")
        ]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"])
    observation_id = UUID(response.json()["observations"][0]["id"])

    with SessionLocal() as db_session:
        srid = db_session.execute(
            text("SELECT ST_SRID(geometry) FROM satellite_observations WHERE id = :observation_id"),
            {"observation_id": observation_id},
        ).scalar_one()

    assert srid == 4326


def test_delete_monitor_cascades_observations(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = monitor["id"]
    monitor_uuid = UUID(monitor_id)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_CASCADE_1", acquired_at="2026-08-15T10:00:00Z")
        ]
    )
    set_provider(provider)
    run_search(client, monitor_id)

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count())
            .select_from(SatelliteObservation)
            .where(SatelliteObservation.monitor_id == monitor_uuid)
        )
    assert count == 0


def test_search_request_valid_request_accepted(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"])

    assert response.status_code == 200


def test_search_request_start_date_after_end_date_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"], start_date="2026-09-02", end_date="2026-09-01")

    assert response.status_code == 422


def test_search_request_invalid_cloud_cover_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"], max_cloud_cover=101)

    assert response.status_code == 422


def test_search_request_invalid_limit_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"], limit=0)

    assert response.status_code == 422


def test_provider_called_with_monitor_geometry(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"])

    assert response.status_code == 200
    assert provider.last_call is not None
    assert provider.last_call["intersects_geometry"]["type"] == "Polygon"


def test_provider_called_with_date_range(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"], start_date="2026-08-01", end_date="2026-08-05")

    assert response.status_code == 200
    assert provider.last_call is not None
    assert provider.last_call["start_datetime"] == datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    assert provider.last_call["end_datetime"].date().isoformat() == "2026-08-05"


def test_provider_called_with_cloud_filter(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, monitor["id"], max_cloud_cover=20)

    assert response.status_code == 200
    assert provider.last_call is not None
    assert provider.last_call["max_cloud_cover"] == 20


def test_normalized_observations_persisted(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(
                item_id="S2A_PERSIST_FIELDS_1",
                acquired_at="2026-08-15T10:00:00Z",
                cloud_cover=8.3,
                platform="Sentinel-2B",
            )
        ]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"])
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 1
    assert body["observations"][0]["item_id"] == "S2A_PERSIST_FIELDS_1"
    assert body["observations"][0]["cloud_cover"] == pytest.approx(8.3)


def test_repeated_search_does_not_duplicate_rows(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_DUPLICATE_1", acquired_at="2026-08-15T10:00:00Z")
        ]
    )
    set_provider(provider)

    first = run_search(client, monitor["id"])
    second = run_search(client, monitor["id"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["inserted_count"] == 1
    assert second.json()["inserted_count"] == 0

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count())
            .select_from(SatelliteObservation)
            .where(SatelliteObservation.monitor_id == monitor_id)
        )
    assert count == 1


def test_missing_cloud_observation_excluded_when_threshold_supplied(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_CLOUD_MISSING", acquired_at="2026-08-15T10:00:00Z", cloud_cover=None),
            build_provider_observation(item_id="S2A_CLOUD_VALID", acquired_at="2026-08-16T10:00:00Z", cloud_cover=15),
        ]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"], max_cloud_cover=20)
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 1
    assert body["observations"][0]["item_id"] == "S2A_CLOUD_VALID"
    assert body["skipped_count"] >= 1


def test_malformed_external_item_skipped_cleanly(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    malformed_item = build_provider_observation(item_id="S2A_MALFORMED", acquired_at="2026-08-15T10:00:00Z")
    malformed_item.pop("item_id")
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_VALID_ITEM", acquired_at="2026-08-16T10:00:00Z"),
            malformed_item,
        ]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"])
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 1
    assert body["observations"][0]["item_id"] == "S2A_VALID_ITEM"
    assert body["skipped_count"] >= 1


def test_provider_failure_returns_502(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(observations=[], raise_error=True)
    set_provider(provider)

    response = run_search(client, monitor["id"])

    assert response.status_code == 502
    assert response.json() == {"detail": "Satellite provider unavailable"}


def test_search_endpoint_returns_normalized_response(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[build_provider_observation(item_id="S2A_RESPONSE_1", acquired_at="2026-08-17T10:00:00Z")]
    )
    set_provider(provider)

    response = run_search(client, monitor["id"])
    body = response.json()

    assert response.status_code == 200
    assert body["monitor_id"] == monitor["id"]
    assert body["provider"] == "planetary_computer"
    assert body["collection"] == "sentinel-2-l2a"
    assert body["count"] == 1


def test_search_missing_monitor_returns_404(client: TestClient) -> None:
    provider = FakeSatelliteProvider(observations=[])
    set_provider(provider)

    response = run_search(client, str(uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_list_stored_observations_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_LIST_1", acquired_at="2026-08-17T10:00:00Z"),
            build_provider_observation(item_id="S2A_LIST_2", acquired_at="2026-08-18T10:00:00Z"),
        ]
    )
    set_provider(provider)
    run_search(client, monitor["id"])

    response = client.get(f"/monitors/{monitor['id']}/observations")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_observation_list_pagination_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_PAGE_1", acquired_at="2026-08-17T10:00:00Z"),
            build_provider_observation(item_id="S2A_PAGE_2", acquired_at="2026-08-18T10:00:00Z"),
            build_provider_observation(item_id="S2A_PAGE_3", acquired_at="2026-08-19T10:00:00Z"),
        ]
    )
    set_provider(provider)
    run_search(client, monitor["id"])

    response = client.get(f"/monitors/{monitor['id']}/observations?limit=1&offset=1")
    body = response.json()

    assert response.status_code == 200
    assert len(body) == 1
    assert body[0]["item_id"] == "S2A_PAGE_2"


def test_observation_list_date_filter_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_DATE_1", acquired_at="2026-08-05T10:00:00Z"),
            build_provider_observation(item_id="S2A_DATE_2", acquired_at="2026-08-20T10:00:00Z"),
        ]
    )
    set_provider(provider)
    run_search(client, monitor["id"], start_date="2026-08-01", end_date="2026-08-30")

    response = client.get(
        f"/monitors/{monitor['id']}/observations?start_date=2026-08-10&end_date=2026-08-30"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["item_id"] == "S2A_DATE_2"


def test_observation_list_cloud_filter_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_CLOUD_FILTER_1", acquired_at="2026-08-10T10:00:00Z", cloud_cover=10),
            build_provider_observation(item_id="S2A_CLOUD_FILTER_2", acquired_at="2026-08-11T10:00:00Z", cloud_cover=50),
        ]
    )
    set_provider(provider)
    run_search(client, monitor["id"], max_cloud_cover=100)

    response = client.get(f"/monitors/{monitor['id']}/observations?max_cloud_cover=20")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["item_id"] == "S2A_CLOUD_FILTER_1"


def test_observation_list_platform_filter_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[
            build_provider_observation(item_id="S2A_PLATFORM_A", acquired_at="2026-08-10T10:00:00Z", platform="sentinel-2a"),
            build_provider_observation(item_id="S2A_PLATFORM_B", acquired_at="2026-08-11T10:00:00Z", platform="sentinel-2b"),
        ]
    )
    set_provider(provider)
    run_search(client, monitor["id"])

    response = client.get(f"/monitors/{monitor['id']}/observations?platform=sentinel-2a")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["item_id"] == "S2A_PLATFORM_A"


def test_get_observation_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[build_provider_observation(item_id="S2A_GET_ONE", acquired_at="2026-08-10T10:00:00Z")]
    )
    set_provider(provider)
    search_response = run_search(client, monitor["id"])
    observation_id = search_response.json()["observations"][0]["id"]

    response = client.get(f"/monitors/{monitor['id']}/observations/{observation_id}")

    assert response.status_code == 200
    assert response.json()["id"] == observation_id


def test_get_observation_wrong_monitor_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="Monitor One")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="Monitor Two")
    provider = FakeSatelliteProvider(
        observations=[build_provider_observation(item_id="S2A_WRONG_OWNER", acquired_at="2026-08-10T10:00:00Z")]
    )
    set_provider(provider)
    search_response = run_search(client, monitor_one["id"])
    observation_id = search_response.json()["observations"][0]["id"]

    response = client.get(f"/monitors/{monitor_two['id']}/observations/{observation_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Observation not found"}


def test_get_observation_unknown_observation_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{monitor['id']}/observations/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Observation not found"}


def test_get_observation_invalid_uuid_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{monitor['id']}/observations/not-a-uuid")

    assert response.status_code == 422


def test_observation_geometry_returned_as_geojson(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[build_provider_observation(item_id="S2A_GEOJSON", acquired_at="2026-08-10T10:00:00Z")]
    )
    set_provider(provider)
    search_response = run_search(client, monitor["id"])
    observation = search_response.json()["observations"][0]

    assert observation["geometry"]["type"] == "Polygon"
    assert isinstance(observation["geometry"]["coordinates"], list)


def test_observation_assets_returned_as_structured_json(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeSatelliteProvider(
        observations=[build_provider_observation(item_id="S2A_ASSETS", acquired_at="2026-08-10T10:00:00Z")]
    )
    set_provider(provider)
    search_response = run_search(client, monitor["id"])
    assets = search_response.json()["observations"][0]["assets"]

    assert "B04" in assets
    assert "href" in assets["B04"]
    assert "roles" in assets["B04"]


def test_monitor_crud_regression_still_works(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = created["id"]

    get_response = client.get(f"/monitors/{monitor_id}")
    patch_response = client.patch(f"/monitors/{monitor_id}", json={"name": "Updated Regression Monitor"})
    delete_response = client.delete(f"/monitors/{monitor_id}")

    assert get_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] == "Updated Regression Monitor"
    assert delete_response.status_code == 204


def test_monitor_summary_and_intersection_regression_still_work(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    created = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = created["id"]

    summary_response = client.get(f"/monitors/{monitor_id}/summary")
    intersection_response = client.post(
        f"/monitors/{monitor_id}/intersects",
        json={"geometry": deepcopy(OVERLAP_GEOMETRY)},
    )

    assert summary_response.status_code == 200
    assert summary_response.json()["srid"] == 4326
    assert intersection_response.status_code == 200
    assert "intersects" in intersection_response.json()


def test_health_regression_still_works(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_ready_regression_still_works(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
