from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from app.api.routes import monitors as monitor_routes
from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import (
    ChangeAnalysis,
    ChangeEvent,
    ChangeEventSemanticAnalysis,
    Monitor,
    PreparedObservation,
    SatelliteObservation,
)
from app.schemas import AnalysisSemanticComputeResponse, ChangeEventSemanticAnalysisRead, SemanticLabel
from app.services.semantic_service import BulkSemanticComputationResult, EventSemanticComputationResult

MONITOR_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-80.852, 35.221], [-80.847, 35.221], [-80.847, 35.226], [-80.852, 35.226], [-80.852, 35.221]]],
}

EVENT_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-80.8508, 35.2222], [-80.8498, 35.2222], [-80.8498, 35.2232], [-80.8508, 35.2232], [-80.8508, 35.2222]]],
}


def build_monitor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Semantic Test Monitor",
        "description": "Monitor for semantic endpoint tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 10.0,
    }
    payload.update(overrides)
    return payload


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> UUID:
    response = client.post("/monitors", json=build_monitor_payload(**overrides))
    assert response.status_code == 201
    monitor_id = UUID(response.json()["id"])
    created_monitor_ids.append(monitor_id)
    return monitor_id


def seed_event_graph(monitor_id: UUID) -> tuple[UUID, UUID, UUID, UUID]:
    with SessionLocal() as db_session:
        before_observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"SEM-BEFORE-{uuid4()}",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
            cloud_cover=12.0,
            geometry=geojson_geometry_to_wkb(EVENT_POLYGON),
            bbox=[-80.8508, 35.2222, -80.8498, 35.2232],
            assets={"B04": {"href": "https://example.test/b04.tif"}},
            metadata_={},
        )
        after_observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"SEM-AFTER-{uuid4()}",
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
            cloud_cover=14.0,
            geometry=geojson_geometry_to_wkb(EVENT_POLYGON),
            bbox=[-80.8508, 35.2222, -80.8498, 35.2232],
            assets={"B04": {"href": "https://example.test/b04.tif"}},
            metadata_={},
        )
        db_session.add_all([before_observation, after_observation])
        db_session.flush()

        before_prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=before_observation.id,
            status="ready",
            storage_uri="file:///tmp/semantic-before/multispectral.tif",
            valid_mask_uri="file:///tmp/semantic-before/valid-mask.tif",
            preview_uri="file:///tmp/semantic-before/preview.png",
            crs="EPSG:32617",
            resolution_m=10.0,
            width=128,
            height=128,
            band_names=["B02", "B03", "B04", "B08", "B11", "B12"],
            cloud_fraction=0.1,
            valid_fraction=0.9,
            processing_metadata={"source": "test"},
        )
        after_prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=after_observation.id,
            status="ready",
            storage_uri="file:///tmp/semantic-after/multispectral.tif",
            valid_mask_uri="file:///tmp/semantic-after/valid-mask.tif",
            preview_uri="file:///tmp/semantic-after/preview.png",
            crs="EPSG:32617",
            resolution_m=10.0,
            width=128,
            height=128,
            band_names=["B02", "B03", "B04", "B08", "B11", "B12"],
            cloud_fraction=0.1,
            valid_fraction=0.9,
            processing_metadata={"source": "test"},
        )
        db_session.add_all([before_prepared, after_prepared])
        db_session.flush()

        analysis = ChangeAnalysis(
            monitor_id=monitor_id,
            before_prepared_id=before_prepared.id,
            after_prepared_id=after_prepared.id,
            status="ready",
            algorithm="baseline_change",
            algorithm_version="v1",
            threshold=0.3,
            minimum_change_area_m2=10.0,
            changed_pixel_count=10,
            valid_pixel_count=200,
            changed_fraction=0.05,
            changed_area_m2=200.0,
            statistics={"coverage": 1.0},
            change_score_uri="file:///tmp/semantic-analysis/change-score.tif",
            change_mask_uri="file:///tmp/semantic-analysis/change-mask.tif",
            valid_comparison_mask_uri="file:///tmp/semantic-analysis/valid-mask.tif",
            preview_uri="file:///tmp/semantic-analysis/preview.png",
        )
        db_session.add(analysis)
        db_session.flush()

        event = ChangeEvent(
            monitor_id=monitor_id,
            analysis_id=analysis.id,
            geometry=geojson_geometry_to_wkb(EVENT_POLYGON),
            area_m2=1000.0,
            perimeter_m=120.0,
            confidence=0.82,
            severity="medium",
            mean_change_score=0.44,
            max_change_score=0.91,
            mean_abs_delta_ndvi=0.17,
            mean_spectral_distance=0.21,
            pixel_count=24,
            first_detected_at=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
            last_detected_at=datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc),
            status="new",
            properties={},
        )
        db_session.add(event)
        db_session.commit()

        return analysis.id, event.id, before_prepared.id, after_prepared.id


def build_semantic_summary(
    *,
    event_id: UUID,
    analysis_id: UUID,
    before_prepared_id: UUID,
    after_prepared_id: UUID,
) -> ChangeEventSemanticAnalysisRead:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    return ChangeEventSemanticAnalysisRead(
        id=uuid4(),
        change_event_id=event_id,
        change_analysis_id=analysis_id,
        before_prepared_observation_id=before_prepared_id,
        after_prepared_observation_id=after_prepared_id,
        semantic_label=SemanticLabel.VEGETATION_DECREASE,
        semantic_confidence=0.71,
        abstained=False,
        model_name="torchgeo_resnet18_sentinel2_rgb_moco",
        model_version="resnet18_sentinel2_rgb_moco-e3a335e3",
        inference_method="hybrid_rule_v1",
        before_land_cover="Tree cover",
        after_land_cover=None,
        before_ndvi_mean=0.61,
        after_ndvi_mean=0.42,
        ndvi_delta=-0.19,
        before_ndwi_mean=0.18,
        after_ndwi_mean=0.13,
        ndwi_delta=-0.05,
        before_nbr_mean=0.32,
        after_nbr_mean=0.24,
        nbr_delta=-0.08,
        before_built_up_score=0.11,
        after_built_up_score=0.16,
        built_up_delta=0.05,
        embedding_distance=0.27,
        valid_pixel_coverage=0.83,
        explanation=["Semantic evidence confidence reflects agreement and signal strength."],
        evidence={"version": "semantic-evidence-v1"},
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> Generator[list[UUID], None, None]:
    ids: list[UUID] = []
    yield ids

    if ids:
        with SessionLocal() as db_session:
            db_session.execute(delete(Monitor).where(Monitor.id.in_(ids)))
            db_session.commit()


def test_compute_event_semantics_endpoint_is_idempotent(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id, before_prepared_id, after_prepared_id = seed_event_graph(monitor_id)
    summary = build_semantic_summary(
        event_id=event_id,
        analysis_id=analysis_id,
        before_prepared_id=before_prepared_id,
        after_prepared_id=after_prepared_id,
    )

    call_counter = {"count": 0}

    def fake_compute(*_: object, **kwargs: object) -> EventSemanticComputationResult:
        force_recompute = bool(kwargs.get("force_recompute", False))
        call_counter["count"] += 1
        if call_counter["count"] == 1 or force_recompute:
            return EventSemanticComputationResult(summary=summary, computed=True)
        return EventSemanticComputationResult(summary=summary, computed=False)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(monitor_routes, "compute_change_event_semantics", fake_compute)

    try:
        first = client.post(f"/monitors/{monitor_id}/events/{event_id}/semantics")
        second = client.post(f"/monitors/{monitor_id}/events/{event_id}/semantics")
        forced = client.post(f"/monitors/{monitor_id}/events/{event_id}/semantics?force_recompute=true")
    finally:
        monkeypatch.undo()

    assert first.status_code == 201
    assert first.json()["computed"] is True

    assert second.status_code == 200
    assert second.json()["computed"] is False

    assert forced.status_code == 201
    assert forced.json()["computed"] is True


def test_get_event_semantics_endpoint_and_404_behavior(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id, before_prepared_id, after_prepared_id = seed_event_graph(monitor_id)
    summary = build_semantic_summary(
        event_id=event_id,
        analysis_id=analysis_id,
        before_prepared_id=before_prepared_id,
        after_prepared_id=after_prepared_id,
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(monitor_routes, "get_change_event_semantic_analysis", lambda *args, **kwargs: summary)
    try:
        ok_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/semantics")
    finally:
        monkeypatch.undo()

    assert ok_response.status_code == 200
    assert ok_response.json()["semantic_label"] == "vegetation_decrease"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(monitor_routes, "get_change_event_semantic_analysis", lambda *args, **kwargs: None)
    try:
        missing_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/semantics")
    finally:
        monkeypatch.undo()

    assert missing_response.status_code == 404


def test_compute_analysis_semantics_endpoint(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, _, _, _ = seed_event_graph(monitor_id)

    def fake_bulk(*_: object, **__: object) -> BulkSemanticComputationResult:
        return BulkSemanticComputationResult(
            response=AnalysisSemanticComputeResponse(
                analysis_id=analysis_id,
                event_count=3,
                computed=2,
                reused=1,
                failed=0,
                elapsed_seconds=0.82,
            )
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(monitor_routes, "compute_analysis_semantics", fake_bulk)

    try:
        response = client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/semantics")
    finally:
        monkeypatch.undo()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"] == str(analysis_id)
    assert body["computed"] == 2
    assert body["reused"] == 1


def test_list_events_semantic_filter_validation_and_passthrough(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    captured: dict[str, str | None] = {"semantic_label": None}

    def fake_list(*_: object, **kwargs: object) -> list[dict[str, object]]:
        captured["semantic_label"] = kwargs.get("semantic_label") if isinstance(kwargs.get("semantic_label"), str) else None
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(monitor_routes, "list_change_events", fake_list)
    try:
        response = client.get(f"/monitors/{monitor_id}/events?semantic_label=VEGETATION_INCREASE")
    finally:
        monkeypatch.undo()

    assert response.status_code == 200
    assert captured["semantic_label"] == "vegetation_increase"

    invalid = client.get(f"/monitors/{monitor_id}/events?semantic_label=not_a_label")
    assert invalid.status_code == 422


def test_change_event_semantic_model_constraints(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id, before_prepared_id, after_prepared_id = seed_event_graph(monitor_id)

    with SessionLocal() as db_session:
        row = ChangeEventSemanticAnalysis(
            change_event_id=event_id,
            change_analysis_id=analysis_id,
            before_prepared_observation_id=before_prepared_id,
            after_prepared_observation_id=after_prepared_id,
            semantic_label="vegetation_decrease",
            semantic_confidence=0.66,
            abstained=False,
            model_name="torchgeo_resnet18_sentinel2_rgb_moco",
            model_version="resnet18_sentinel2_rgb_moco-e3a335e3",
            inference_method="hybrid_rule_v1",
            evidence={"version": "semantic-evidence-v1"},
            valid_pixel_coverage=0.75,
        )
        db_session.add(row)
        db_session.commit()

        duplicate = ChangeEventSemanticAnalysis(
            change_event_id=event_id,
            change_analysis_id=analysis_id,
            before_prepared_observation_id=before_prepared_id,
            after_prepared_observation_id=after_prepared_id,
            semantic_label="vegetation_decrease",
            semantic_confidence=0.60,
            abstained=False,
            model_name="torchgeo_resnet18_sentinel2_rgb_moco",
            model_version="resnet18_sentinel2_rgb_moco-e3a335e3",
            inference_method="hybrid_rule_v1",
            evidence={"version": "semantic-evidence-v1"},
            valid_pixel_coverage=0.70,
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        invalid_confidence = ChangeEventSemanticAnalysis(
            change_event_id=event_id,
            change_analysis_id=analysis_id,
            before_prepared_observation_id=before_prepared_id,
            after_prepared_observation_id=after_prepared_id,
            semantic_label="vegetation_increase",
            semantic_confidence=1.1,
            abstained=False,
            model_name="torchgeo_resnet18_sentinel2_rgb_moco",
            model_version="resnet18_sentinel2_rgb_moco-e3a335e3",
            inference_method="hybrid_rule_v1-test-conf",
            evidence={"version": "semantic-evidence-v1"},
            valid_pixel_coverage=0.70,
        )
        db_session.add(invalid_confidence)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_monitor_delete_cascades_semantic_rows(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id, before_prepared_id, after_prepared_id = seed_event_graph(monitor_id)

    with SessionLocal() as db_session:
        db_session.add(
            ChangeEventSemanticAnalysis(
                change_event_id=event_id,
                change_analysis_id=analysis_id,
                before_prepared_observation_id=before_prepared_id,
                after_prepared_observation_id=after_prepared_id,
                semantic_label="uncertain",
                semantic_confidence=0.3,
                abstained=True,
                model_name="torchgeo_resnet18_sentinel2_rgb_moco",
                model_version="resnet18_sentinel2_rgb_moco-e3a335e3",
                inference_method="hybrid_rule_v1",
                evidence={"version": "semantic-evidence-v1"},
                valid_pixel_coverage=0.12,
            )
        )
        db_session.commit()

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204
    created_monitor_ids.remove(monitor_id)

    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM change_event_semantic_analyses WHERE change_event_id = :event_id"),
            {"event_id": event_id},
        ).scalar_one()

    assert count == 0
