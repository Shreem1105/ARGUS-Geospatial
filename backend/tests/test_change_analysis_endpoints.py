from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_origin
from sqlalchemy import delete, func, select

import app.services.change_analysis_service as analysis_service
import app.services.prepared_observation_service as prepared_service
from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import ChangeAnalysis, Monitor, PreparedObservation, SatelliteObservation
from app.processing import ChangeDetectionError

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


@pytest.fixture(scope="module")
def monitor_bounds_utm() -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    xs: list[float] = []
    ys: list[float] = []
    for longitude, latitude in MONITOR_POLYGON["coordinates"][0]:
        x, y = transformer.transform(longitude, latitude)
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


def build_monitor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Change Analysis Test Monitor",
        "description": "Monitor for change analysis endpoint tests",
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


def _file_uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(url2pathname(unquote(parsed.path)))


def _build_assets() -> dict[str, dict[str, object]]:
    return {
        "B02": {"href": "https://example.com/B02.tif", "media_type": "image/tiff; application=geotiff", "roles": ["data"]},
        "B03": {"href": "https://example.com/B03.tif", "media_type": "image/tiff; application=geotiff", "roles": ["data"]},
        "B04": {"href": "https://example.com/B04.tif", "media_type": "image/tiff; application=geotiff", "roles": ["data"]},
        "B08": {"href": "https://example.com/B08.tif", "media_type": "image/tiff; application=geotiff", "roles": ["data"]},
        "SCL": {"href": "https://example.com/SCL.tif", "media_type": "image/tiff; application=geotiff", "roles": ["data"]},
    }


def _write_prepared_artifacts(
    *,
    root: Path,
    folder_name: str,
    transform: rasterio.Affine,
    width: int,
    height: int,
    change_slice: tuple[slice, slice] | None = None,
    change_delta: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> tuple[Path, Path, Path]:
    target = root / folder_name
    target.mkdir(parents=True, exist_ok=True)

    stack = np.stack(
        [
            np.full((height, width), 0.10, dtype=np.float32),
            np.full((height, width), 0.12, dtype=np.float32),
            np.full((height, width), 0.14, dtype=np.float32),
            np.full((height, width), 0.20, dtype=np.float32),
        ]
    )

    if change_slice is not None:
        rows, cols = change_slice
        for band_index, delta in enumerate(change_delta):
            stack[band_index, rows, cols] += np.float32(delta)

    multispectral_path = target / "multispectral.tif"
    valid_mask_path = target / "valid_mask.tif"
    preview_path = target / "preview.png"

    with rasterio.open(
        multispectral_path,
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

    from PIL import Image

    Image.fromarray(np.full((height, width, 3), 120, dtype=np.uint8), mode="RGB").save(preview_path)

    return multispectral_path, valid_mask_path, preview_path


def insert_prepared_observation(
    *,
    monitor_id: UUID,
    item_id: str,
    acquired_at: datetime,
    cloud_cover: float,
    local_cloud_fraction: float,
    valid_fraction: float,
    transform: rasterio.Affine,
    data_root: Path,
    status: str = "ready",
    change_slice: tuple[slice, slice] | None = None,
    change_delta: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> UUID:
    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=item_id,
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=acquired_at,
            cloud_cover=cloud_cover,
            geometry=geojson_geometry_to_wkb(deepcopy(OBSERVATION_GEOMETRY)),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            thumbnail_url="https://example.com/thumb.jpg",
            assets=_build_assets(),
            metadata_={"processing:level": "Level-2A", "proj:epsg": 32617},
        )
        db_session.add(observation)
        db_session.flush()

        storage_uri = None
        valid_mask_uri = None
        preview_uri = None
        width = None
        height = None
        if status == "ready":
            multispectral_path, valid_mask_path, preview_path = _write_prepared_artifacts(
                root=data_root,
                folder_name=f"{monitor_id}/{observation.id}",
                transform=transform,
                width=220,
                height=220,
                change_slice=change_slice,
                change_delta=change_delta,
            )
            storage_uri = multispectral_path.resolve().as_uri()
            valid_mask_uri = valid_mask_path.resolve().as_uri()
            preview_uri = preview_path.resolve().as_uri()
            width = 220
            height = 220

        prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=observation.id,
            status=status,
            storage_uri=storage_uri,
            valid_mask_uri=valid_mask_uri,
            preview_uri=preview_uri,
            crs="EPSG:32617" if status == "ready" else None,
            resolution_m=10.0 if status == "ready" else None,
            width=width,
            height=height,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=local_cloud_fraction,
            valid_fraction=valid_fraction,
            nodata_value=-9999.0,
            processing_metadata={"processing_version": "sentinel2-preprocess-v1"},
        )
        db_session.add(prepared)
        db_session.commit()
        db_session.refresh(prepared)
        return prepared.id


def create_default_prepared_pair(
    *,
    monitor_id: UUID,
    data_root: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
    before_item_id: str = "S2_BEFORE",
    after_item_id: str = "S2_AFTER",
) -> tuple[UUID, UUID]:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_prepared_id = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id=before_item_id,
        acquired_at=datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc),
        cloud_cover=12.0,
        local_cloud_fraction=0.10,
        valid_fraction=0.92,
        transform=transform,
        data_root=data_root,
    )

    after_prepared_id = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id=after_item_id,
        acquired_at=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
        cloud_cover=8.0,
        local_cloud_fraction=0.08,
        valid_fraction=0.95,
        transform=transform,
        data_root=data_root,
        change_slice=(slice(90, 130), slice(90, 130)),
        change_delta=(0.10, 0.10, 0.08, 0.16),
    )

    return before_prepared_id, after_prepared_id


def analysis_payload(before_prepared_id: UUID, after_prepared_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "before_prepared_id": str(before_prepared_id),
        "after_prepared_id": str(after_prepared_id),
        "threshold": 0.30,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)
    return payload


def test_manual_analysis_creation_succeeds(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["algorithm"] == "spectral-ndvi-baseline"
    assert body["algorithm_version"] == "v1"
    assert body["changed_pixel_count"] is not None
    assert body["valid_pixel_count"] is not None

    change_score_path = _file_uri_to_path(body["change_score_uri"])
    change_mask_path = _file_uri_to_path(body["change_mask_uri"])
    valid_comparison_mask_path = _file_uri_to_path(body["valid_comparison_mask_uri"])
    preview_path = _file_uri_to_path(body["preview_uri"])

    assert change_score_path.exists()
    assert change_mask_path.exists()
    assert valid_comparison_mask_path.exists()
    assert preview_path.exists()

    with SessionLocal() as db_session:
        count = db_session.scalar(select(func.count()).select_from(ChangeAnalysis).where(ChangeAnalysis.monitor_id == monitor_id))
    assert count == 1


def test_reversed_chronology_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_REV",
        after_item_id="S2_AFTER_REV",
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(after_prepared_id, before_prepared_id),
    )

    assert response.status_code == 422


def test_same_product_comparison_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, _ = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_SAME",
        after_item_id="S2_AFTER_SAME",
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, before_prepared_id),
    )

    assert response.status_code == 422


def test_wrong_monitor_ownership_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="Monitor One")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="Monitor Two")

    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=UUID(monitor_one["id"]),
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_OWNER",
        after_item_id="S2_AFTER_OWNER",
    )

    response = client.post(
        f"/monitors/{monitor_two['id']}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert response.status_code == 404


def test_non_ready_prepared_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_prepared_id = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_BEFORE_FAILED",
        acquired_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        cloud_cover=10.0,
        local_cloud_fraction=0.10,
        valid_fraction=0.90,
        transform=transform,
        data_root=tmp_path,
        status="failed",
    )

    after_prepared_id = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_AFTER_READY",
        acquired_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        cloud_cover=10.0,
        local_cloud_fraction=0.10,
        valid_fraction=0.90,
        transform=transform,
        data_root=tmp_path,
        status="ready",
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert response.status_code == 409


def test_duplicate_analysis_reused(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_REUSE",
        after_item_id="S2_AFTER_REUSE",
    )

    first = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )
    second = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    with SessionLocal() as db_session:
        count = db_session.scalar(select(func.count()).select_from(ChangeAnalysis).where(ChangeAnalysis.monitor_id == monitor_id))
    assert count == 1


def test_missing_analysis_artifact_triggers_repair(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_REPAIR_ANALYSIS",
        after_item_id="S2_AFTER_REPAIR_ANALYSIS",
    )

    first = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )
    assert first.status_code == 201

    change_score_path = _file_uri_to_path(first.json()["change_score_uri"])
    change_score_path.unlink()

    second = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert second.status_code == 201
    assert change_score_path.exists()

    with SessionLocal() as db_session:
        count = db_session.scalar(select(func.count()).select_from(ChangeAnalysis).where(ChangeAnalysis.monitor_id == monitor_id))
    assert count == 1


def test_processing_failure_marks_analysis_failed(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_FAIL",
        after_item_id="S2_AFTER_FAIL",
    )

    def _raise_change_error(**_: object):
        raise ChangeDetectionError("simulated failure")

    monkeypatch.setattr(analysis_service, "run_change_detection", _raise_change_error)

    response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )

    assert response.status_code == 500

    with SessionLocal() as db_session:
        analysis = db_session.execute(select(ChangeAnalysis).where(ChangeAnalysis.monitor_id == monitor_id)).scalar_one()

    assert analysis.status == "failed"
    assert analysis.statistics["last_error"]["type"] == "processing_error"


def test_auto_pair_selects_expected_prepared_products(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_low_quality = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_BEFORE_LOW",
        acquired_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        cloud_cover=20.0,
        local_cloud_fraction=0.18,
        valid_fraction=0.70,
        transform=transform,
        data_root=tmp_path,
        status="ready",
    )
    before_best = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_BEFORE_BEST",
        acquired_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        cloud_cover=12.0,
        local_cloud_fraction=0.12,
        valid_fraction=0.95,
        transform=transform,
        data_root=tmp_path,
        status="ready",
    )

    after_best_valid = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_AFTER_BEST_VALID",
        acquired_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        cloud_cover=10.0,
        local_cloud_fraction=0.18,
        valid_fraction=0.97,
        transform=transform,
        data_root=tmp_path,
        status="ready",
        change_slice=(slice(90, 130), slice(90, 130)),
        change_delta=(0.08, 0.08, 0.08, 0.15),
    )
    _after_lower_valid = insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_AFTER_LOWER_VALID",
        acquired_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        cloud_cover=8.0,
        local_cloud_fraction=0.05,
        valid_fraction=0.90,
        transform=transform,
        data_root=tmp_path,
        status="ready",
        change_slice=(slice(100, 120), slice(100, 120)),
        change_delta=(0.08, 0.08, 0.08, 0.15),
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses/auto",
        json={
            "before_start_date": "2026-05-01",
            "before_end_date": "2026-06-30",
            "after_start_date": "2026-08-01",
            "after_end_date": "2026-08-31",
            "max_local_cloud_fraction": 0.20,
            "threshold": 0.30,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["before_prepared_id"] == str(before_best)
    assert body["after_prepared_id"] == str(after_best_valid)
    assert body["before_prepared_id"] != str(before_low_quality)


def test_auto_pair_no_valid_pair_returns_409(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_BEFORE_TOO_CLOUDY",
        acquired_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        cloud_cover=40.0,
        local_cloud_fraction=0.50,
        valid_fraction=0.90,
        transform=transform,
        data_root=tmp_path,
        status="ready",
    )
    insert_prepared_observation(
        monitor_id=monitor_id,
        item_id="S2_AFTER_TOO_CLOUDY",
        acquired_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        cloud_cover=40.0,
        local_cloud_fraction=0.60,
        valid_fraction=0.90,
        transform=transform,
        data_root=tmp_path,
        status="ready",
        change_slice=(slice(90, 130), slice(90, 130)),
        change_delta=(0.10, 0.10, 0.10, 0.10),
    )

    response = client.post(
        f"/monitors/{monitor_id}/analyses/auto",
        json={
            "before_start_date": "2026-05-01",
            "before_end_date": "2026-06-30",
            "after_start_date": "2026-08-01",
            "after_end_date": "2026-08-31",
            "max_local_cloud_fraction": 0.20,
            "threshold": 0.30,
        },
    )

    assert response.status_code == 409


def test_list_and_get_analysis_endpoints(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=monitor_id,
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_LIST_GET",
        after_item_id="S2_AFTER_LIST_GET",
    )

    create_response = client.post(
        f"/monitors/{monitor_id}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )
    assert create_response.status_code == 201
    analysis_id = create_response.json()["id"]

    list_response = client.get(f"/monitors/{monitor_id}/analyses?limit=50&offset=0")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(f"/monitors/{monitor_id}/analyses/{analysis_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == analysis_id


def test_get_analysis_wrong_monitor_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="Monitor A")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="Monitor B")
    before_prepared_id, after_prepared_id = create_default_prepared_pair(
        monitor_id=UUID(monitor_one["id"]),
        data_root=tmp_path,
        monitor_bounds_utm=monitor_bounds_utm,
        before_item_id="S2_BEFORE_OWNER2",
        after_item_id="S2_AFTER_OWNER2",
    )

    create_response = client.post(
        f"/monitors/{monitor_one['id']}/analyses",
        json=analysis_payload(before_prepared_id, after_prepared_id),
    )
    assert create_response.status_code == 201
    analysis_id = create_response.json()["id"]

    get_response = client.get(f"/monitors/{monitor_two['id']}/analyses/{analysis_id}")

    assert get_response.status_code == 404


def test_get_unknown_analysis_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{monitor['id']}/analyses/{uuid4()}")

    assert response.status_code == 404


def test_invalid_analysis_uuid_returns_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.get(f"/monitors/{monitor['id']}/analyses/not-a-uuid")

    assert response.status_code == 422


def test_list_analyses_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.get(f"/monitors/{uuid4()}/analyses")
    assert response.status_code == 404


def test_root_health_ready_regression(client: TestClient) -> None:
    root_response = client.get("/")
    health_response = client.get("/health")
    ready_response = client.get("/ready")

    assert root_response.status_code == 200
    assert health_response.status_code == 200
    assert ready_response.status_code == 200
