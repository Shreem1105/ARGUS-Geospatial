from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import rasterio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

import app.services.prepared_observation_service as prepared_service
from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import Monitor, PreparedObservation, SatelliteObservation
from app.processing import PreparedRasterResult, RasterAssetError, RasterPreparationError

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


@pytest.fixture(autouse=True)
def isolate_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prepared_service, "_data_root", lambda: tmp_path)


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
        "name": "Prepared Observation Test Monitor",
        "description": "Monitor for prepared observation tests",
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


def build_assets() -> dict[str, dict[str, object]]:
    return {
        "B02": {
            "href": "https://example.com/B02.tif",
            "media_type": "image/tiff; application=geotiff",
            "roles": ["data"],
            "title": "Blue",
        },
        "B03": {
            "href": "https://example.com/B03.tif",
            "media_type": "image/tiff; application=geotiff",
            "roles": ["data"],
            "title": "Green",
        },
        "B04": {
            "href": "https://example.com/B04.tif",
            "media_type": "image/tiff; application=geotiff",
            "roles": ["data"],
            "title": "Red",
        },
        "B08": {
            "href": "https://example.com/B08.tif",
            "media_type": "image/tiff; application=geotiff",
            "roles": ["data"],
            "title": "NIR",
        },
        "SCL": {
            "href": "https://example.com/SCL.tif",
            "media_type": "image/tiff; application=geotiff",
            "roles": ["data"],
            "title": "Scene Classification",
        },
    }


def insert_observation(*, monitor_id: UUID, item_id: str = "S2_OBS_PREP_1") -> UUID:
    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=item_id,
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
            cloud_cover=11.5,
            geometry=geojson_geometry_to_wkb(OBSERVATION_GEOMETRY),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            thumbnail_url="https://example.com/thumbnail.jpg",
            assets=build_assets(),
            metadata_={"proj:epsg": 32617, "gsd": 10},
        )
        db_session.add(observation)
        db_session.commit()
        db_session.refresh(observation)
        return observation.id


def insert_prepared_observation(*, monitor_id: UUID, observation_id: UUID, **overrides: object) -> UUID:
    with SessionLocal() as db_session:
        prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            status="ready",
            storage_uri="file:///tmp/multispectral.tif",
            valid_mask_uri="file:///tmp/valid_mask.tif",
            preview_uri="file:///tmp/preview.png",
            crs="EPSG:32617",
            resolution_m=10.0,
            width=100,
            height=120,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.2,
            valid_fraction=0.7,
            nodata_value=-9999.0,
            processing_metadata={"source_item_id": "S2_OBS_PREP_1"},
        )

        for key, value in overrides.items():
            setattr(prepared, key, value)

        db_session.add(prepared)
        db_session.commit()
        db_session.refresh(prepared)
        return prepared.id


def build_prepare_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"force_reprocess": False}
    payload.update(overrides)
    return payload


def _file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(url2pathname(unquote(parsed.path)))


def install_fake_prepare_success(monkeypatch: pytest.MonkeyPatch, *, call_log: list[dict[str, object]]) -> None:
    def _fake_prepare(**kwargs: object) -> PreparedRasterResult:
        call_log.append(kwargs)
        target_directory = kwargs["target_directory"]
        assert isinstance(target_directory, Path)
        target_directory.mkdir(parents=True, exist_ok=True)

        storage_path = target_directory / "multispectral.tif"
        valid_mask_path = target_directory / "valid_mask.tif"
        preview_path = target_directory / "preview.png"

        width = 40
        height = 20
        transform = rasterio.transform.from_origin(500000.0, 3900000.0, 10.0, 10.0)

        stack = np.stack(
            [
                np.full((height, width), 0.10, dtype=np.float32),
                np.full((height, width), 0.12, dtype=np.float32),
                np.full((height, width), 0.14, dtype=np.float32),
                np.full((height, width), 0.20, dtype=np.float32),
            ]
        )

        with rasterio.open(
            storage_path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=4,
            dtype="float32",
            crs="EPSG:32617",
            transform=transform,
            nodata=-9999.0,
            compress="deflate",
        ) as destination:
            for index in range(1, 5):
                destination.write(stack[index - 1], indexes=index)

        valid_mask = np.ones((height, width), dtype=np.uint8)
        with rasterio.open(
            valid_mask_path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs="EPSG:32617",
            transform=transform,
            nodata=0,
            compress="deflate",
        ) as destination:
            destination.write(valid_mask, indexes=1)

        preview_data = np.full((height, width, 3), 80, dtype=np.uint8)
        Image.fromarray(preview_data, mode="RGB").save(preview_path)

        return PreparedRasterResult(
            storage_path=storage_path,
            valid_mask_path=valid_mask_path,
            preview_path=preview_path,
            crs="EPSG:32617",
            resolution_m=10.0,
            width=width,
            height=height,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.15,
            valid_fraction=0.72,
            nodata_value=-9999.0,
            processing_metadata={
                "source_item_id": kwargs["item_id"],
                "resampling": {"continuous": "bilinear", "scl": "nearest"},
            },
        )

    monkeypatch.setattr(prepared_service, "prepare_sentinel2_raster", _fake_prepare)


def test_prepared_unique_constraint_rejects_duplicates(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id)

    insert_prepared_observation(monitor_id=monitor_id, observation_id=observation_id)
    with pytest.raises(IntegrityError):
        insert_prepared_observation(monitor_id=monitor_id, observation_id=observation_id)


def test_prepared_cloud_fraction_below_zero_rejected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_CLOUD_LOW")

    with pytest.raises(IntegrityError):
        insert_prepared_observation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            cloud_fraction=-0.1,
        )


def test_prepared_cloud_fraction_above_one_rejected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_CLOUD_HIGH")

    with pytest.raises(IntegrityError):
        insert_prepared_observation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            cloud_fraction=1.2,
        )


def test_prepared_valid_fraction_above_one_rejected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_VALID_HIGH")

    with pytest.raises(IntegrityError):
        insert_prepared_observation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            valid_fraction=1.1,
        )


def test_prepared_monitor_fk_enforced() -> None:
    with pytest.raises(IntegrityError):
        insert_prepared_observation(
            monitor_id=uuid4(),
            observation_id=uuid4(),
        )


def test_prepared_observation_fk_enforced(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    with pytest.raises(IntegrityError):
        insert_prepared_observation(
            monitor_id=monitor_id,
            observation_id=uuid4(),
        )


def test_delete_monitor_cascades_prepared_observations(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_CASCADE_PREP")
    insert_prepared_observation(monitor_id=monitor_id, observation_id=observation_id)

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count()).select_from(PreparedObservation).where(PreparedObservation.monitor_id == monitor_id)
        )
    assert count == 0


def test_prepare_endpoint_creates_ready_record(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id)
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["observation_id"] == str(observation_id)
    assert body["band_names"] == ["B02", "B03", "B04", "B08"]
    assert body["valid_fraction"] == pytest.approx(0.72)
    assert body["cloud_fraction"] == pytest.approx(0.15)
    assert len(call_log) == 1


def test_prepare_missing_monitor_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    observation_id = insert_observation(monitor_id=UUID(monitor["id"]), item_id="S2_NOT_FOUND")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    response = client.post(
        f"/monitors/{uuid4()}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Observation not found"}
    assert len(call_log) == 0


def test_prepare_wrong_monitor_observation_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="M1")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="M2")
    observation_id = insert_observation(monitor_id=UUID(monitor_one["id"]), item_id="S2_WRONG_MONITOR")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    response = client.post(
        f"/monitors/{monitor_two['id']}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Observation not found"}
    assert len(call_log) == 0


def test_prepare_invalid_observation_uuid_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.post(
        f"/monitors/{monitor['id']}/observations/not-a-uuid/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 422


def test_prepare_idempotent_without_force(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_IDEMPOTENT")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    first = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    second = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(call_log) == 1

    with SessionLocal() as db_session:
        count = db_session.scalar(
            select(func.count())
            .select_from(PreparedObservation)
            .where(PreparedObservation.monitor_id == monitor_id)
        )
    assert count == 1



def test_prepare_missing_multispectral_artifact_triggers_repair(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_REPAIR_STORAGE")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    first_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert first_response.status_code == 200

    storage_path = _file_uri_to_path(first_response.json()["storage_uri"])
    storage_path.unlink()

    second_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "ready"
    assert len(call_log) == 2


def test_prepare_missing_valid_mask_artifact_triggers_repair(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_REPAIR_MASK")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    first_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert first_response.status_code == 200

    mask_path = _file_uri_to_path(first_response.json()["valid_mask_uri"])
    mask_path.unlink()

    second_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "ready"
    assert len(call_log) == 2


def test_prepare_missing_preview_artifact_triggers_repair(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_REPAIR_PREVIEW")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    first_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert first_response.status_code == 200

    preview_path = _file_uri_to_path(first_response.json()["preview_uri"])
    preview_path.unlink()

    second_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "ready"
    assert len(call_log) == 2
def test_prepare_force_reprocess_runs_again(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_FORCE")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    first = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    second = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(force_reprocess=True),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(call_log) == 2


def test_prepare_provider_failure_returns_502_and_marks_failed(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_FAIL_PROVIDER")

    def _raise_provider(**_: object) -> PreparedRasterResult:
        raise RasterAssetError("signed asset fetch failed")

    monkeypatch.setattr(prepared_service, "prepare_sentinel2_raster", _raise_provider)

    response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Satellite asset provider unavailable"}

    with SessionLocal() as db_session:
        prepared = db_session.execute(
            select(PreparedObservation).where(
                PreparedObservation.monitor_id == monitor_id,
                PreparedObservation.observation_id == observation_id,
            )
        ).scalar_one()

    assert prepared.status == "failed"
    assert prepared.processing_metadata["last_error"]["type"] == "provider_error"


def test_prepare_processing_failure_returns_500_and_marks_failed(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_FAIL_PROCESS")

    def _raise_processing(**_: object) -> PreparedRasterResult:
        raise RasterPreparationError("invalid geometry window")

    monkeypatch.setattr(prepared_service, "prepare_sentinel2_raster", _raise_processing)

    response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to prepare observation raster"}

    with SessionLocal() as db_session:
        prepared = db_session.execute(
            select(PreparedObservation).where(
                PreparedObservation.monitor_id == monitor_id,
                PreparedObservation.observation_id == observation_id,
            )
        ).scalar_one()

    assert prepared.status == "failed"
    assert prepared.processing_metadata["last_error"]["type"] == "processing_error"


def test_prepare_failed_record_can_rerun_with_force(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_FAIL_THEN_OK")

    def _raise_provider(**_: object) -> PreparedRasterResult:
        raise RasterAssetError("temporary provider error")

    monkeypatch.setattr(prepared_service, "prepare_sentinel2_raster", _raise_provider)
    failed_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert failed_response.status_code == 502

    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)
    success_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(force_reprocess=True),
    )

    assert success_response.status_code == 200
    assert success_response.json()["status"] == "ready"
    assert len(call_log) == 1


def test_get_prepared_observation_returns_record(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_GET_PREP")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    prepare_response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert prepare_response.status_code == 200

    get_response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared")
    assert get_response.status_code == 200
    assert get_response.json()["observation_id"] == str(observation_id)
    assert get_response.json()["status"] == "ready"


def test_get_prepared_observation_missing_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    observation_id = insert_observation(monitor_id=UUID(monitor["id"]), item_id="S2_NOT_PREPARED")

    response = client.get(f"/monitors/{monitor['id']}/observations/{observation_id}/prepared")
    assert response.status_code == 404
    assert response.json() == {"detail": "Prepared observation not found"}


def test_get_prepared_wrong_monitor_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="Monitor One")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="Monitor Two")
    observation_id = insert_observation(monitor_id=UUID(monitor_one["id"]), item_id="S2_WRONG_MONITOR_PREP")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    prepare_response = client.post(
        f"/monitors/{monitor_one['id']}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )
    assert prepare_response.status_code == 200

    get_response = client.get(f"/monitors/{monitor_two['id']}/observations/{observation_id}/prepared")
    assert get_response.status_code == 404


def test_get_prepared_invalid_uuid_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{monitor['id']}/observations/not-a-uuid/prepared")
    assert response.status_code == 422


def test_prepare_response_contains_observation_summary(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    observation_id = insert_observation(monitor_id=monitor_id, item_id="S2_SUMMARY")
    call_log: list[dict[str, object]] = []
    install_fake_prepare_success(monkeypatch, call_log=call_log)

    response = client.post(
        f"/monitors/{monitor_id}/observations/{observation_id}/prepare",
        json=build_prepare_payload(),
    )

    assert response.status_code == 200
    observation_summary = response.json()["observation"]
    assert observation_summary["id"] == str(observation_id)
    assert observation_summary["item_id"] == "S2_SUMMARY"
    assert observation_summary["provider"] == "planetary_computer"


def test_prepare_request_validation_invalid_payload_returns_422(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    observation_id = insert_observation(monitor_id=UUID(monitor["id"]), item_id="S2_INVALID_PAYLOAD")

    response = client.post(
        f"/monitors/{monitor['id']}/observations/{observation_id}/prepare",
        json={"force_reprocess": {"invalid": True}},
    )

    assert response.status_code == 422


def test_root_regression_still_works(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_health_regression_still_works(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_ready_regression_still_works(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200



