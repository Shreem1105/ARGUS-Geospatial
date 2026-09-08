from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

import app.services.artifact_service as artifact_service
from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import ChangeAnalysis, Monitor, PreparedObservation, SatelliteObservation

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

OBS_GEOMETRY = {
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
    monkeypatch.setattr(artifact_service, "_data_root", lambda: tmp_path)


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


def _create_monitor(created_monitor_ids: list[UUID]) -> UUID:
    with SessionLocal() as db_session:
        monitor = Monitor(
            name="Artifact Test Monitor",
            description="",
            geometry=geojson_geometry_to_wkb(deepcopy(MONITOR_POLYGON)),
            monitor_type="general",
            sensitivity=0.5,
            minimum_change_area_m2=50.0,
            status="active",
        )
        db_session.add(monitor)
        db_session.commit()
        db_session.refresh(monitor)
        created_monitor_ids.append(monitor.id)
        return monitor.id


def _insert_observation(monitor_id: UUID, item_id: str) -> UUID:
    with SessionLocal() as db_session:
        observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=item_id,
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
            cloud_cover=12.5,
            geometry=geojson_geometry_to_wkb(OBS_GEOMETRY),
            bbox=[-80.849, 35.221, -80.839, 35.231],
            thumbnail_url=None,
            assets={},
            metadata_={},
        )
        db_session.add(observation)
        db_session.commit()
        db_session.refresh(observation)
        return observation.id


def _insert_prepared(
    monitor_id: UUID,
    observation_id: UUID,
    *,
    storage_path: Path,
    mask_path: Path,
    preview_path: Path,
) -> UUID:
    with SessionLocal() as db_session:
        prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            status="ready",
            storage_uri=storage_path.resolve().as_uri(),
            valid_mask_uri=mask_path.resolve().as_uri(),
            preview_uri=preview_path.resolve().as_uri(),
            crs="EPSG:4326",
            resolution_m=10.0,
            width=64,
            height=64,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.15,
            valid_fraction=0.9,
            nodata_value=0.0,
            processing_metadata={},
        )
        db_session.add(prepared)
        db_session.commit()
        db_session.refresh(prepared)
        return prepared.id


def _insert_analysis(
    monitor_id: UUID,
    before_prepared_id: UUID,
    after_prepared_id: UUID,
    *,
    mask_path: Path,
    preview_path: Path,
    score_path: Path,
) -> UUID:
    with SessionLocal() as db_session:
        analysis = ChangeAnalysis(
            monitor_id=monitor_id,
            before_prepared_id=before_prepared_id,
            after_prepared_id=after_prepared_id,
            status="ready",
            algorithm="spectral_change",
            algorithm_version="1.0",
            change_score_uri=score_path.resolve().as_uri(),
            change_mask_uri=mask_path.resolve().as_uri(),
            valid_comparison_mask_uri=mask_path.resolve().as_uri(),
            preview_uri=preview_path.resolve().as_uri(),
            threshold=0.3,
            minimum_change_area_m2=50.0,
            changed_pixel_count=100,
            valid_pixel_count=200,
            changed_fraction=0.5,
            changed_area_m2=1000.0,
            mean_change_score=0.4,
            max_change_score=0.8,
            statistics={
                "abs_delta_ndvi_uri": score_path.resolve().as_uri(),
                "spectral_distance_uri": score_path.resolve().as_uri(),
            },
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)
        return analysis.id


def test_get_prepared_artifact_returns_preview(client: TestClient, created_monitor_ids: list[UUID], tmp_path: Path) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_PREP")

    preview = tmp_path / "prepared" / "preview.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    storage = tmp_path / "prepared" / "stack.tif"
    storage.write_bytes(b"stack")
    mask = tmp_path / "prepared" / "mask.tif"
    mask.write_bytes(b"mask")

    _insert_prepared(
        monitor_id,
        observation_id,
        storage_path=storage,
        mask_path=mask,
        preview_path=preview,
    )

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")
    assert response.status_code == 200
    assert response.content == b"preview"


def test_get_prepared_artifact_outside_data_root_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_OUTSIDE")

    allowed = tmp_path / "prepared"
    allowed.mkdir(parents=True, exist_ok=True)
    storage = allowed / "stack.tif"
    storage.write_bytes(b"stack")
    mask = allowed / "mask.tif"
    mask.write_bytes(b"mask")

    outside = tmp_path.parent / "outside-preview.png"
    outside.write_bytes(b"outside")

    _insert_prepared(
        monitor_id,
        observation_id,
        storage_path=storage,
        mask_path=mask,
        preview_path=outside,
    )

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")
    assert response.status_code == 404
    assert response.json() == {"detail": "Prepared artifact not found"}


def test_get_analysis_artifact_returns_change_mask(client: TestClient, created_monitor_ids: list[UUID], tmp_path: Path) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    before_observation_id = _insert_observation(monitor_id, "S2_ART_BEFORE")
    after_observation_id = _insert_observation(monitor_id, "S2_ART_AFTER")

    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    before_prepared = _insert_prepared(
        monitor_id,
        before_observation_id,
        storage_path=prepared_dir / "before-stack.tif",
        mask_path=prepared_dir / "before-mask.tif",
        preview_path=prepared_dir / "before-preview.png",
    )
    (prepared_dir / "before-stack.tif").write_bytes(b"before-stack")
    (prepared_dir / "before-mask.tif").write_bytes(b"before-mask")
    (prepared_dir / "before-preview.png").write_bytes(b"before-preview")

    after_prepared = _insert_prepared(
        monitor_id,
        after_observation_id,
        storage_path=prepared_dir / "after-stack.tif",
        mask_path=prepared_dir / "after-mask.tif",
        preview_path=prepared_dir / "after-preview.png",
    )
    (prepared_dir / "after-stack.tif").write_bytes(b"after-stack")
    (prepared_dir / "after-mask.tif").write_bytes(b"after-mask")
    (prepared_dir / "after-preview.png").write_bytes(b"after-preview")

    analyses_dir = tmp_path / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    mask = analyses_dir / "change-mask.tif"
    mask.write_bytes(b"change-mask")
    preview = analyses_dir / "analysis-preview.png"
    preview.write_bytes(b"analysis-preview")
    score = analyses_dir / "change-score.tif"
    score.write_bytes(b"change-score")

    analysis_id = _insert_analysis(
        monitor_id,
        before_prepared,
        after_prepared,
        mask_path=mask,
        preview_path=preview,
        score_path=score,
    )

    response = client.get(f"/monitors/{monitor_id}/analyses/{analysis_id}/artifacts/change-mask")
    assert response.status_code == 200
    assert response.content == b"change-mask"


def test_artifact_unknown_kind_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_UNKNOWN")

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/not-a-kind")
    assert response.status_code == 404



def test_get_prepared_artifact_returns_png_content_type(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_PNG")

    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)

    preview = prepared_dir / "preview.png"
    preview.write_bytes(b"png-bytes")
    storage = prepared_dir / "stack.tif"
    storage.write_bytes(b"stack")
    mask = prepared_dir / "mask.tif"
    mask.write_bytes(b"mask")

    _insert_prepared(
        monitor_id,
        observation_id,
        storage_path=storage,
        mask_path=mask,
        preview_path=preview,
    )

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_get_prepared_artifact_missing_prepared_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_MISSING_PREPARED")

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Prepared artifact not found"}


def test_get_prepared_artifact_wrong_monitor_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    other_monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_WRONG_MONITOR")

    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    preview = prepared_dir / "preview.png"
    preview.write_bytes(b"preview")
    storage = prepared_dir / "stack.tif"
    storage.write_bytes(b"stack")
    mask = prepared_dir / "mask.tif"
    mask.write_bytes(b"mask")

    _insert_prepared(
        monitor_id,
        observation_id,
        storage_path=storage,
        mask_path=mask,
        preview_path=preview,
    )

    response = client.get(f"/monitors/{other_monitor_id}/observations/{observation_id}/prepared/artifacts/preview")
    assert response.status_code == 404
    assert response.json() == {"detail": "Prepared artifact not found"}


def test_get_analysis_artifact_unknown_analysis_returns_404(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = _create_monitor(created_monitor_ids)

    response = client.get(f"/monitors/{monitor_id}/analyses/{uuid4()}/artifacts/change-mask")

    assert response.status_code == 404
    assert response.json() == {"detail": "Analysis artifact not found"}


def test_get_analysis_artifact_wrong_monitor_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    other_monitor_id = _create_monitor(created_monitor_ids)
    before_observation_id = _insert_observation(monitor_id, "S2_ART_WRONG_ANALYSIS_BEFORE")
    after_observation_id = _insert_observation(monitor_id, "S2_ART_WRONG_ANALYSIS_AFTER")

    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)

    before_stack = prepared_dir / "before-stack.tif"
    before_mask = prepared_dir / "before-mask.tif"
    before_preview = prepared_dir / "before-preview.png"
    before_stack.write_bytes(b"before-stack")
    before_mask.write_bytes(b"before-mask")
    before_preview.write_bytes(b"before-preview")

    before_prepared = _insert_prepared(
        monitor_id,
        before_observation_id,
        storage_path=before_stack,
        mask_path=before_mask,
        preview_path=before_preview,
    )

    after_stack = prepared_dir / "after-stack.tif"
    after_mask = prepared_dir / "after-mask.tif"
    after_preview = prepared_dir / "after-preview.png"
    after_stack.write_bytes(b"after-stack")
    after_mask.write_bytes(b"after-mask")
    after_preview.write_bytes(b"after-preview")

    after_prepared = _insert_prepared(
        monitor_id,
        after_observation_id,
        storage_path=after_stack,
        mask_path=after_mask,
        preview_path=after_preview,
    )

    analyses_dir = tmp_path / "analyses"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    mask = analyses_dir / "change-mask.tif"
    preview = analyses_dir / "analysis-preview.png"
    score = analyses_dir / "change-score.tif"
    mask.write_bytes(b"mask")
    preview.write_bytes(b"preview")
    score.write_bytes(b"score")

    analysis_id = _insert_analysis(
        monitor_id,
        before_prepared,
        after_prepared,
        mask_path=mask,
        preview_path=preview,
        score_path=score,
    )

    response = client.get(f"/monitors/{other_monitor_id}/analyses/{analysis_id}/artifacts/change-mask")
    assert response.status_code == 404
    assert response.json() == {"detail": "Analysis artifact not found"}


def test_prepared_artifact_path_traversal_style_uri_returns_404(
    client: TestClient,
    created_monitor_ids: list[UUID],
    tmp_path: Path,
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_TRAVERSAL")

    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    storage = prepared_dir / "stack.tif"
    storage.write_bytes(b"stack")
    mask = prepared_dir / "mask.tif"
    mask.write_bytes(b"mask")

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")

    traversal_path = prepared_dir / ".." / outside.name

    with SessionLocal() as db_session:
        prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            status="ready",
            storage_uri=storage.resolve().as_uri(),
            valid_mask_uri=mask.resolve().as_uri(),
            preview_uri=traversal_path.as_uri(),
            crs="EPSG:4326",
            resolution_m=10.0,
            width=64,
            height=64,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.15,
            valid_fraction=0.9,
            nodata_value=0.0,
            processing_metadata={},
        )
        db_session.add(prepared)
        db_session.commit()

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Prepared artifact not found"}


def test_artifact_invalid_uuid_returns_422(client: TestClient) -> None:
    response = client.get("/monitors/not-a-uuid/observations/not-a-uuid/prepared/artifacts/preview")
    assert response.status_code == 422


def test_artifact_404_response_does_not_leak_local_paths(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = _create_monitor(created_monitor_ids)
    observation_id = _insert_observation(monitor_id, "S2_ART_NO_LEAK")

    response = client.get(f"/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview")
    body = response.text

    assert response.status_code == 404
    assert "W:\\\\" not in body
    assert "C:\\\\" not in body
    assert "Prepared artifact not found" in body

