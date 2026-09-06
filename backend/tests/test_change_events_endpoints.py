from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import ChangeAnalysis, ChangeEvent, Monitor, PreparedObservation, SatelliteObservation
from app.processing import EVENT_GENERATION_VERSION, NODATA_VALUE

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


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Change Event Test Monitor",
        "description": "Monitor for change event endpoint tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "event-test",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 100.0,
    }
    payload.update(overrides)

    response = client.post("/monitors", json=payload)
    assert response.status_code == 201

    body = response.json()
    created_monitor_ids.append(UUID(body["id"]))
    return body


def _write_single_band(
    path: Path,
    array: np.ndarray,
    *,
    transform: rasterio.Affine,
    crs: str,
    dtype: str,
    nodata: float | int,
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=array.shape[1],
        height=array.shape[0],
        count=1,
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as destination:
        destination.write(array.astype(dtype), indexes=1)


def _seed_analysis(
    *,
    monitor_id: UUID,
    base_dir: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
    analysis_status: str = "ready",
    zero_change: bool = False,
) -> dict[str, object]:
    base_dir.mkdir(parents=True, exist_ok=True)
    analysis_id = uuid4()
    before_prepared_id = uuid4()
    after_prepared_id = uuid4()

    before_observation_id = uuid4()
    after_observation_id = uuid4()

    before_time = datetime(2026, 7, 12, 16, 8, 21, tzinfo=timezone.utc)
    after_time = datetime(2026, 8, 23, 16, 8, 21, 25000, tzinfo=timezone.utc)

    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x, max_y, 10.0, 10.0)

    height = 60
    width = 60

    change_mask = np.zeros((height, width), dtype=np.uint8)
    change_score = np.full((height, width), NODATA_VALUE, dtype=np.float32)
    valid_mask = np.ones((height, width), dtype=np.uint8)
    abs_delta_ndvi = np.full((height, width), NODATA_VALUE, dtype=np.float32)
    spectral_distance = np.full((height, width), NODATA_VALUE, dtype=np.float32)

    if not zero_change:
        change_mask[8:14, 8:14] = 1
        change_mask[24:27, 30:35] = 1

        change_score[8:14, 8:14] = 0.75
        change_score[24:27, 30:35] = 0.45

        abs_delta_ndvi[8:14, 8:14] = 0.28
        abs_delta_ndvi[24:27, 30:35] = 0.12

        spectral_distance[8:14, 8:14] = 0.24
        spectral_distance[24:27, 30:35] = 0.09

    change_score_path = base_dir / "change_score.tif"
    change_mask_path = base_dir / "change_mask.tif"
    valid_mask_path = base_dir / "valid_comparison_mask.tif"
    abs_delta_path = base_dir / "abs_delta_ndvi.tif"
    spectral_path = base_dir / "spectral_distance.tif"
    preview_path = base_dir / "preview.png"

    _write_single_band(change_score_path, change_score, transform=transform, crs="EPSG:32617", dtype="float32", nodata=NODATA_VALUE)
    _write_single_band(change_mask_path, change_mask, transform=transform, crs="EPSG:32617", dtype="uint8", nodata=0)
    _write_single_band(valid_mask_path, valid_mask, transform=transform, crs="EPSG:32617", dtype="uint8", nodata=0)
    _write_single_band(abs_delta_path, abs_delta_ndvi, transform=transform, crs="EPSG:32617", dtype="float32", nodata=NODATA_VALUE)
    _write_single_band(spectral_path, spectral_distance, transform=transform, crs="EPSG:32617", dtype="float32", nodata=NODATA_VALUE)

    Image.fromarray(np.full((80, 120, 3), 80, dtype=np.uint8), mode="RGB").save(preview_path)

    changed_pixels = int(np.count_nonzero(change_mask == 1))
    valid_pixels = int(np.count_nonzero(valid_mask == 1))
    valid_scores = change_score[change_mask == 1]

    with SessionLocal() as db_session:
        before_obs = SatelliteObservation(
            id=before_observation_id,
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"S2_BEFORE_{before_observation_id}",
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=before_time,
            cloud_cover=8.5,
            geometry=geojson_geometry_to_wkb(OBSERVATION_GEOMETRY),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            thumbnail_url="https://example.com/before-thumb.jpg",
            assets={"B04": {"href": "https://example.com/b04.tif"}},
            metadata_={"processing:level": "L2A"},
        )
        after_obs = SatelliteObservation(
            id=after_observation_id,
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"S2_AFTER_{after_observation_id}",
            platform="sentinel-2c",
            sensor="MSI",
            acquired_at=after_time,
            cloud_cover=4.0,
            geometry=geojson_geometry_to_wkb(OBSERVATION_GEOMETRY),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            thumbnail_url="https://example.com/after-thumb.jpg",
            assets={"B04": {"href": "https://example.com/b04.tif"}},
            metadata_={"processing:level": "L2A"},
        )

        before_prepared = PreparedObservation(
            id=before_prepared_id,
            monitor_id=monitor_id,
            observation_id=before_observation_id,
            status="ready",
            storage_uri=(base_dir / "before_multispectral.tif").resolve().as_uri(),
            valid_mask_uri=(base_dir / "before_valid_mask.tif").resolve().as_uri(),
            preview_uri=(base_dir / "before_preview.png").resolve().as_uri(),
            crs="EPSG:32617",
            resolution_m=10.0,
            width=width,
            height=height,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.10,
            valid_fraction=0.90,
            nodata_value=NODATA_VALUE,
            processing_metadata={"processing_version": "sentinel2-preprocess-v1"},
        )

        after_prepared = PreparedObservation(
            id=after_prepared_id,
            monitor_id=monitor_id,
            observation_id=after_observation_id,
            status="ready",
            storage_uri=(base_dir / "after_multispectral.tif").resolve().as_uri(),
            valid_mask_uri=(base_dir / "after_valid_mask.tif").resolve().as_uri(),
            preview_uri=(base_dir / "after_preview.png").resolve().as_uri(),
            crs="EPSG:32617",
            resolution_m=10.0,
            width=width,
            height=height,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.12,
            valid_fraction=0.88,
            nodata_value=NODATA_VALUE,
            processing_metadata={"processing_version": "sentinel2-preprocess-v1"},
        )

        analysis = ChangeAnalysis(
            id=analysis_id,
            monitor_id=monitor_id,
            before_prepared_id=before_prepared_id,
            after_prepared_id=after_prepared_id,
            status=analysis_status,
            algorithm="spectral-ndvi-baseline",
            algorithm_version="v1",
            change_score_uri=change_score_path.resolve().as_uri(),
            change_mask_uri=change_mask_path.resolve().as_uri(),
            valid_comparison_mask_uri=valid_mask_path.resolve().as_uri(),
            preview_uri=preview_path.resolve().as_uri(),
            threshold=0.30,
            minimum_change_area_m2=100.0,
            changed_pixel_count=changed_pixels,
            valid_pixel_count=valid_pixels,
            changed_fraction=(changed_pixels / valid_pixels if valid_pixels > 0 else 0.0),
            changed_area_m2=changed_pixels * 100.0,
            mean_change_score=(float(np.mean(valid_scores)) if valid_scores.size > 0 else 0.0),
            max_change_score=(float(np.max(valid_scores)) if valid_scores.size > 0 else 0.0),
            statistics={
                "mean_abs_delta_ndvi": (float(np.mean(abs_delta_ndvi[change_mask == 1])) if changed_pixels > 0 else 0.0),
                "mean_spectral_distance": (float(np.mean(spectral_distance[change_mask == 1])) if changed_pixels > 0 else 0.0),
                "supporting_rasters": {
                    "abs_delta_ndvi_uri": abs_delta_path.resolve().as_uri(),
                    "spectral_distance_uri": spectral_path.resolve().as_uri(),
                },
            },
        )

        db_session.add(before_obs)
        db_session.add(after_obs)
        db_session.add(before_prepared)
        db_session.add(after_prepared)
        db_session.add(analysis)
        db_session.commit()

    return {
        "analysis_id": analysis_id,
        "change_mask_path": change_mask_path,
        "change_score_path": change_score_path,
        "valid_mask_path": valid_mask_path,
        "abs_delta_path": abs_delta_path,
        "spectral_path": spectral_path,
        "after_time": after_time,
    }


def _generate_events(client: TestClient, monitor_id: UUID, analysis_id: UUID):
    return client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/events")


def test_ready_analysis_generates_events(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_a", monitor_bounds_utm=monitor_bounds_utm)

    response = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert response.status_code == 201
    body = response.json()
    assert body["count"] == len(body["events"])
    assert body["count"] > 0
    assert body["generated"] is True


def test_duplicate_generation_returns_existing(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_b", monitor_bounds_utm=monitor_bounds_utm)

    first = _generate_events(client, monitor_id, seeded["analysis_id"])
    second = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["count"] == second.json()["count"]
    assert second.json()["generated"] is False


def test_non_ready_analysis_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(
        monitor_id=monitor_id,
        base_dir=tmp_path / "analysis_c",
        monitor_bounds_utm=monitor_bounds_utm,
        analysis_status="processing",
    )

    response = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert response.status_code == 409


def test_missing_mask_is_controlled_failure(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_d", monitor_bounds_utm=monitor_bounds_utm)

    Path(seeded["change_mask_path"]).unlink()
    response = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert response.status_code == 409


def test_corrupt_mask_is_controlled_failure(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_e", monitor_bounds_utm=monitor_bounds_utm)

    Path(seeded["change_mask_path"]).write_bytes(b"not-a-raster")
    response = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert response.status_code == 409


def test_zero_change_generation_succeeds(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(
        monitor_id=monitor_id,
        base_dir=tmp_path / "analysis_zero",
        monitor_bounds_utm=monitor_bounds_utm,
        zero_change=True,
    )

    first = _generate_events(client, monitor_id, seeded["analysis_id"])
    second = _generate_events(client, monitor_id, seeded["analysis_id"])

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["count"] == 0
    assert second.json()["count"] == 0


def test_generation_version_recorded(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_version", monitor_bounds_utm=monitor_bounds_utm)

    response = _generate_events(client, monitor_id, seeded["analysis_id"])
    assert response.status_code == 201

    with SessionLocal() as db_session:
        analysis = db_session.execute(select(ChangeAnalysis).where(ChangeAnalysis.id == seeded["analysis_id"])).scalar_one()
        generation = analysis.statistics["event_generation"]

    assert generation["version"] == EVENT_GENERATION_VERSION


def test_analysis_event_list_returns_empty_before_generation(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_list_empty", monitor_bounds_utm=monitor_bounds_utm)

    response = client.get(f"/monitors/{monitor_id}/analyses/{seeded['analysis_id']}/events")

    assert response.status_code == 200
    assert response.json() == []


def test_list_and_detail_endpoints_with_filters(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_filters", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    assert generate_response.status_code == 201
    events = generate_response.json()["events"]
    event_id = events[0]["id"]

    list_response = client.get(f"/monitors/{monitor_id}/events?limit=50&offset=0")
    assert list_response.status_code == 200
    assert len(list_response.json()) == len(events)

    detail_response = client.get(f"/monitors/{monitor_id}/events/{event_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == event_id

    by_analysis_response = client.get(f"/monitors/{monitor_id}/analyses/{seeded['analysis_id']}/events")
    assert by_analysis_response.status_code == 200
    assert len(by_analysis_response.json()) == len(events)

    severity_response = client.get(f"/monitors/{monitor_id}/events?severity=low")
    assert severity_response.status_code == 200

    confidence_response = client.get(f"/monitors/{monitor_id}/events?min_confidence=0")
    assert confidence_response.status_code == 200

    area_response = client.get(f"/monitors/{monitor_id}/events?min_area_m2=100")
    assert area_response.status_code == 200

    analysis_filter_response = client.get(f"/monitors/{monitor_id}/events?analysis_id={seeded['analysis_id']}")
    assert analysis_filter_response.status_code == 200
    assert len(analysis_filter_response.json()) == len(events)

    pagination_response = client.get(f"/monitors/{monitor_id}/events?limit=1&offset=0")
    assert pagination_response.status_code == 200
    assert len(pagination_response.json()) == 1


def test_status_filter_and_patch_preserves_scientific_fields(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_patch", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    event = generate_response.json()["events"][0]
    event_id = event["id"]

    patch_response = client.patch(
        f"/monitors/{monitor_id}/events/{event_id}",
        json={"status": "reviewed"},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["status"] == "reviewed"
    assert patched["updated_at"] != event["updated_at"]
    assert patched["geometry"] == event["geometry"]
    assert patched["area_m2"] == event["area_m2"]
    assert patched["confidence"] == event["confidence"]
    assert patched["severity"] == event["severity"]

    status_filter_response = client.get(f"/monitors/{monitor_id}/events?status=reviewed")
    assert status_filter_response.status_code == 200
    assert any(item["id"] == event_id for item in status_filter_response.json())


def test_patch_invalid_status_and_extra_fields_rejected(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_patch_invalid", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    event_id = generate_response.json()["events"][0]["id"]

    invalid_status = client.patch(
        f"/monitors/{monitor_id}/events/{event_id}",
        json={"status": "not-real"},
    )
    assert invalid_status.status_code == 422

    extra_field = client.patch(
        f"/monitors/{monitor_id}/events/{event_id}",
        json={"status": "reviewed", "geometry": MONITOR_POLYGON},
    )
    assert extra_field.status_code == 422


def test_event_spatial_summary_and_intersection(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_summary", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    event = generate_response.json()["events"][0]
    event_id = event["id"]

    summary_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["geometry_type"] == "Polygon"
    assert summary["srid"] == 4326
    assert summary["area_m2"] > 0
    assert summary["perimeter_m"] > 0

    overlap_response = client.post(
        f"/monitors/{monitor_id}/events/intersects",
        json={"geometry": event["geometry"]},
    )
    assert overlap_response.status_code == 200
    assert any(item["id"] == event_id for item in overlap_response.json())

    non_overlap_response = client.post(
        f"/monitors/{monitor_id}/events/intersects",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-80.8410, 35.2201],
                        [-80.8404, 35.2201],
                        [-80.8404, 35.2206],
                        [-80.8410, 35.2206],
                        [-80.8410, 35.2201],
                    ]
                ],
            }
        },
    )
    assert non_overlap_response.status_code == 200
    assert all(item["id"] != event_id for item in non_overlap_response.json())


def test_monitor_event_summary_aggregation(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_monitor_summary", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    assert generate_response.status_code == 201

    summary_response = client.get(f"/monitors/{monitor_id}/events/summary")
    assert summary_response.status_code == 200

    summary = summary_response.json()
    assert summary["monitor_id"] == str(monitor_id)
    assert summary["total_events"] == generate_response.json()["count"]
    assert summary["total_changed_area_m2"] > 0
    assert summary["by_status"]["new"] >= 1
    assert summary["by_severity"]["low"] >= 1


def test_wrong_monitor_ownership_and_unknown_event(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor_one = create_monitor_and_track(client, created_monitor_ids, name="Monitor One")
    monitor_two = create_monitor_and_track(client, created_monitor_ids, name="Monitor Two")

    monitor_one_id = UUID(monitor_one["id"])
    monitor_two_id = UUID(monitor_two["id"])

    seeded = _seed_analysis(monitor_id=monitor_one_id, base_dir=tmp_path / "analysis_owner", monitor_bounds_utm=monitor_bounds_utm)
    generate_response = _generate_events(client, monitor_one_id, seeded["analysis_id"])
    event_id = generate_response.json()["events"][0]["id"]

    wrong_owner_detail = client.get(f"/monitors/{monitor_two_id}/events/{event_id}")
    assert wrong_owner_detail.status_code == 404

    wrong_owner_generate = client.post(f"/monitors/{monitor_two_id}/analyses/{seeded['analysis_id']}/events")
    assert wrong_owner_generate.status_code == 404

    unknown_event = client.get(f"/monitors/{monitor_one_id}/events/{uuid4()}")
    assert unknown_event.status_code == 404


def test_invalid_uuid_paths_return_422(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    detail_response = client.get(f"/monitors/{monitor_id}/events/not-a-uuid")
    assert detail_response.status_code == 422

    patch_response = client.patch(
        f"/monitors/{monitor_id}/events/not-a-uuid",
        json={"status": "reviewed"},
    )
    assert patch_response.status_code == 422


def test_change_event_geometry_srid_and_postgis_index(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_srid", monitor_bounds_utm=monitor_bounds_utm)

    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    event_id = UUID(generate_response.json()["events"][0]["id"])

    with SessionLocal() as db_session:
        srid = db_session.execute(text("SELECT ST_SRID(geometry) FROM change_events WHERE id = :event_id"), {"event_id": event_id}).scalar_one()
        geometry_type = db_session.execute(text("SELECT GeometryType(geometry) FROM change_events WHERE id = :event_id"), {"event_id": event_id}).scalar_one()
        is_valid = db_session.execute(text("SELECT ST_IsValid(geometry) FROM change_events WHERE id = :event_id"), {"event_id": event_id}).scalar_one()

        index_exists = db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'ix_change_events_geometry_gist'
                """
            )
        ).scalar_one()

    assert srid == 4326
    assert geometry_type == "POLYGON"
    assert is_valid is True
    assert int(index_exists) == 1


def test_constraints_confidence_and_non_negative_fields(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_constraints", monitor_bounds_utm=monitor_bounds_utm)

    with SessionLocal() as db_session:
        analysis = db_session.execute(select(ChangeAnalysis).where(ChangeAnalysis.id == seeded["analysis_id"])).scalar_one()

        invalid_event = ChangeEvent(
            id=uuid4(),
            monitor_id=monitor_id,
            analysis_id=analysis.id,
            geometry=geojson_geometry_to_wkb(MONITOR_POLYGON),
            area_m2=-1.0,
            perimeter_m=10.0,
            confidence=1.2,
            severity="low",
            mean_change_score=0.5,
            max_change_score=0.7,
            mean_abs_delta_ndvi=0.2,
            mean_spectral_distance=0.2,
            pixel_count=5,
            first_detected_at=datetime.now(tz=timezone.utc),
            last_detected_at=datetime.now(tz=timezone.utc),
            status="new",
            properties={},
        )
        db_session.add(invalid_event)
        with pytest.raises(SQLAlchemyError):
            db_session.commit()
        db_session.rollback()


def test_monitor_and_analysis_foreign_keys_enforced() -> None:
    with SessionLocal() as db_session:
        event = ChangeEvent(
            id=uuid4(),
            monitor_id=uuid4(),
            analysis_id=uuid4(),
            geometry=geojson_geometry_to_wkb(MONITOR_POLYGON),
            area_m2=100.0,
            perimeter_m=40.0,
            confidence=0.5,
            severity="low",
            mean_change_score=0.4,
            max_change_score=0.5,
            mean_abs_delta_ndvi=0.1,
            mean_spectral_distance=0.1,
            pixel_count=4,
            first_detected_at=datetime.now(tz=timezone.utc),
            last_detected_at=datetime.now(tz=timezone.utc),
            status="new",
            properties={},
        )
        db_session.add(event)
        with pytest.raises(SQLAlchemyError):
            db_session.commit()
        db_session.rollback()


def test_delete_monitor_cascades_events(
    client: TestClient,
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    monitor_response = client.post(
        "/monitors",
        json={
            "name": "Cascade Monitor",
            "description": "Cascade test",
            "geometry": MONITOR_POLYGON,
            "monitor_type": "cascade",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 100.0,
        },
    )
    assert monitor_response.status_code == 201
    monitor_id = UUID(monitor_response.json()["id"])

    seeded = _seed_analysis(monitor_id=monitor_id, base_dir=tmp_path / "analysis_cascade", monitor_bounds_utm=monitor_bounds_utm)
    generate_response = _generate_events(client, monitor_id, seeded["analysis_id"])
    assert generate_response.status_code == 201

    with SessionLocal() as db_session:
        event_count_before = db_session.execute(
            select(func.count(ChangeEvent.id)).where(ChangeEvent.monitor_id == monitor_id)
        ).scalar_one()
    assert int(event_count_before) > 0

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    with SessionLocal() as db_session:
        obs_count = db_session.execute(select(func.count(SatelliteObservation.id)).where(SatelliteObservation.monitor_id == monitor_id)).scalar_one()
        prepared_count = db_session.execute(select(func.count(PreparedObservation.id)).where(PreparedObservation.monitor_id == monitor_id)).scalar_one()
        analysis_count = db_session.execute(select(func.count(ChangeAnalysis.id)).where(ChangeAnalysis.monitor_id == monitor_id)).scalar_one()
        event_count = db_session.execute(select(func.count(ChangeEvent.id)).where(ChangeEvent.monitor_id == monitor_id)).scalar_one()

    assert int(obs_count) == 0
    assert int(prepared_count) == 0
    assert int(analysis_count) == 0
    assert int(event_count) == 0


def test_root_health_ready_regression(client: TestClient) -> None:
    root_response = client.get("/")
    health_response = client.get("/health")
    ready_response = client.get("/ready")

    assert root_response.status_code == 200
    assert health_response.status_code == 200
    assert ready_response.status_code == 200
