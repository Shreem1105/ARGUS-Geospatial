from __future__ import annotations

import json
from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import ChangeAnalysis, ChangeEvent, ContextFeature, Monitor, PreparedObservation, SatelliteObservation

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
        "name": "Impact Test Monitor",
        "description": "Monitor for impact tests",
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


def seed_event_graph(monitor_id: UUID, *, severity: str = "medium") -> tuple[UUID, UUID]:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as db_session:
        before_observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"S2-BEFORE-{uuid4()}",
            platform="sentinel-2a",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            cloud_cover=10.0,
            geometry=geojson_geometry_to_wkb(EVENT_POLYGON),
            bbox=[-80.8508, 35.2222, -80.8498, 35.2232],
            assets={"B04": {"href": "https://example.test/b04.tif"}},
            metadata_={},
        )
        after_observation = SatelliteObservation(
            monitor_id=monitor_id,
            provider="planetary_computer",
            collection="sentinel-2-l2a",
            item_id=f"S2-AFTER-{uuid4()}",
            platform="sentinel-2b",
            sensor="MSI",
            acquired_at=datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
            cloud_cover=12.0,
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
            storage_uri="file:///tmp/before/multispectral.tif",
            valid_mask_uri="file:///tmp/before/valid_mask.tif",
            preview_uri="file:///tmp/before/preview.png",
            crs="EPSG:32617",
            resolution_m=10.0,
            width=100,
            height=100,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.1,
            valid_fraction=0.9,
            processing_metadata={"processing_version": "test"},
        )
        after_prepared = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=after_observation.id,
            status="ready",
            storage_uri="file:///tmp/after/multispectral.tif",
            valid_mask_uri="file:///tmp/after/valid_mask.tif",
            preview_uri="file:///tmp/after/preview.png",
            crs="EPSG:32617",
            resolution_m=10.0,
            width=100,
            height=100,
            band_names=["B02", "B03", "B04", "B08"],
            cloud_fraction=0.1,
            valid_fraction=0.9,
            processing_metadata={"processing_version": "test"},
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
            valid_pixel_count=100,
            changed_fraction=0.1,
            changed_area_m2=100.0,
            mean_change_score=0.45,
            max_change_score=0.77,
            statistics={"source": "test"},
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
            severity=severity,
            mean_change_score=0.45,
            max_change_score=0.77,
            mean_abs_delta_ndvi=0.25,
            mean_spectral_distance=0.31,
            pixel_count=56,
            first_detected_at=now,
            last_detected_at=now,
            status="new",
            properties={},
        )
        db_session.add(event)
        db_session.commit()
        return analysis.id, event.id


def insert_context_feature(
    *,
    monitor_id: UUID,
    provider_feature_id: str,
    feature_type: str,
    feature_subtype: str | None,
    geometry: dict[str, object],
    name: str | None,
    properties: dict[str, object],
) -> UUID:
    with SessionLocal() as db_session:
        feature = ContextFeature(
            monitor_id=monitor_id,
            provider="openstreetmap",
            provider_feature_id=provider_feature_id,
            feature_type=feature_type,
            feature_subtype=feature_subtype,
            name=name,
            geometry=geojson_geometry_to_wkb(geometry),
            properties=properties,
        )
        db_session.add(feature)
        db_session.commit()
        return feature.id


def seed_context_features(monitor_id: UUID) -> None:
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/road-intersect",
        feature_type="road",
        feature_subtype="primary",
        geometry={"type": "LineString", "coordinates": [[-80.8512, 35.2227], [-80.8494, 35.2227]]},
        name="Primary Cross",
        properties={"highway": "primary", "road_class": "primary"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/road-near",
        feature_type="road",
        feature_subtype="residential",
        geometry={"type": "LineString", "coordinates": [[-80.8512, 35.22355], [-80.8494, 35.22355]]},
        name="Nearby Road",
        properties={"highway": "residential", "road_class": "residential"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/road-far",
        feature_type="road",
        feature_subtype="service",
        geometry={"type": "LineString", "coordinates": [[-80.8512, 35.2255], [-80.8494, 35.2255]]},
        name="Far Road",
        properties={"highway": "service", "road_class": "service"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/building-intersect",
        feature_type="building",
        feature_subtype="building",
        geometry={"type": "Polygon", "coordinates": [[[-80.8504, 35.2226], [-80.8499, 35.2226], [-80.8499, 35.22305], [-80.8504, 35.22305], [-80.8504, 35.2226]]]},
        name="Intersecting Building",
        properties={"building": "yes"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/building-near",
        feature_type="building",
        feature_subtype="building",
        geometry={"type": "Polygon", "coordinates": [[[-80.8504, 35.22345], [-80.8499, 35.22345], [-80.8499, 35.2238], [-80.8504, 35.2238], [-80.8504, 35.22345]]]},
        name="Nearby Building",
        properties={"building": "yes"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/water-intersect",
        feature_type="waterway",
        feature_subtype="stream",
        geometry={"type": "LineString", "coordinates": [[-80.8502, 35.2219], [-80.8502, 35.2235]]},
        name="Intersecting Stream",
        properties={"waterway": "stream"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/water-near",
        feature_type="waterway",
        feature_subtype="ditch",
        geometry={"type": "LineString", "coordinates": [[-80.8494, 35.2220], [-80.8494, 35.2234]]},
        name="Nearby Ditch",
        properties={"waterway": "ditch"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="relation/admin-city",
        feature_type="administrative",
        feature_subtype="city",
        geometry={"type": "Polygon", "coordinates": [[[-80.8530, 35.2200], [-80.8460, 35.2200], [-80.8460, 35.2270], [-80.8530, 35.2270], [-80.8530, 35.2200]]]},
        name="Charlotte",
        properties={"admin_level": "8", "boundary": "administrative", "place": "city"},
    )
    insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="relation/admin-county",
        feature_type="administrative",
        feature_subtype="county",
        geometry={"type": "Polygon", "coordinates": [[[-80.8600, 35.2150], [-80.8400, 35.2150], [-80.8400, 35.2350], [-80.8600, 35.2350], [-80.8600, 35.2150]]]},
        name="Mecklenburg County",
        properties={"admin_level": "6", "boundary": "administrative", "place": "county"},
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


def test_compute_event_impact_and_summary_metrics(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)
    seed_context_features(monitor_id)

    response = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert response.status_code == 201

    summary = response.json()["summary"]
    assert summary["roads"]["intersecting_count"] == 1
    assert summary["roads"]["nearby_count"] == 1
    assert summary["roads"]["intersecting_length_m"] > 0
    assert summary["roads"]["nearest_distance_m"] == 0
    assert summary["roads"]["classes"]["primary"] == 1
    assert summary["buildings"]["intersecting_count"] == 1
    assert summary["buildings"]["intersection_area_m2"] > 0
    assert summary["waterways"]["intersecting_count"] == 1
    assert "stream" in summary["waterways"]["subtypes"]


def test_event_impact_endpoint_idempotent_and_unique(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)
    seed_context_features(monitor_id)

    first = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    second = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["computed"] is False

    with SessionLocal() as db_session:
        duplicates = db_session.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "SELECT event_id, context_feature_id, impact_type, COUNT(*) AS c "
                "FROM change_event_impacts WHERE event_id = :event_id "
                "GROUP BY event_id, context_feature_id, impact_type HAVING COUNT(*) > 1"
                ") d"
            ),
            {"event_id": event_id},
        ).scalar_one()

    assert duplicates == 0


def test_get_event_impact_and_scientific_severity_unchanged(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id, severity="high")
    seed_context_features(monitor_id)

    with SessionLocal() as db_session:
        before = db_session.execute(text("SELECT severity FROM change_events WHERE id = :event_id"), {"event_id": event_id}).scalar_one()

    compute = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert compute.status_code == 201

    get_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert get_response.status_code == 200
    assert get_response.json()["scientific_severity"] == "high"

    with SessionLocal() as db_session:
        after = db_session.execute(text("SELECT severity FROM change_events WHERE id = :event_id"), {"event_id": event_id}).scalar_one()

    assert before == "high"
    assert after == "high"


def test_event_impact_errors_for_missing_context_and_unknown_event(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)

    no_context = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert no_context.status_code == 409

    seed_context_features(monitor_id)
    unknown = client.post(f"/monitors/{monitor_id}/events/{uuid4()}/impact")
    assert unknown.status_code == 404


def test_bulk_analysis_impact_and_monitor_summary(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id = seed_event_graph(monitor_id)
    seed_context_features(monitor_id)

    with SessionLocal() as db_session:
        event_two = ChangeEvent(
            monitor_id=monitor_id,
            analysis_id=analysis_id,
            geometry=geojson_geometry_to_wkb(EVENT_POLYGON),
            area_m2=950.0,
            perimeter_m=112.0,
            confidence=0.71,
            severity="high",
            mean_change_score=0.5,
            max_change_score=0.8,
            mean_abs_delta_ndvi=0.2,
            mean_spectral_distance=0.25,
            pixel_count=30,
            first_detected_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            last_detected_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
            status="new",
            properties={},
        )
        db_session.add(event_two)
        db_session.commit()

    bulk = client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/impact")
    assert bulk.status_code == 200
    assert bulk.json()["event_count"] == 2
    assert bulk.json()["computed"] == 2
    assert bulk.json()["impact_relationship_count"] > 0

    monitor_summary = client.get(f"/monitors/{monitor_id}/impact/summary")
    assert monitor_summary.status_code == 200
    body = monitor_summary.json()
    assert body["events_with_intersecting_roads"] >= 1
    assert body["unique_intersecting_buildings"] >= 1
    assert body["events_near_waterways"] >= 1

    # ensure GET endpoint returns for one computed event
    get_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert get_response.status_code == 200


def test_change_event_and_context_feature_delete_cascade_impacts(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)
    road_id = insert_context_feature(
        monitor_id=monitor_id,
        provider_feature_id="way/cascade-road",
        feature_type="road",
        feature_subtype="primary",
        geometry={"type": "LineString", "coordinates": [[-80.8512, 35.2227], [-80.8494, 35.2227]]},
        name="Cascade Road",
        properties={"highway": "primary", "road_class": "primary"},
    )

    first = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert first.status_code == 201

    with SessionLocal() as db_session:
        initial = db_session.execute(text("SELECT COUNT(*) FROM change_event_impacts WHERE event_id = :event_id"), {"event_id": event_id}).scalar_one()
        assert initial > 0
        db_session.execute(delete(ContextFeature).where(ContextFeature.id == road_id))
        db_session.commit()

    with SessionLocal() as db_session:
        after_feature_delete = db_session.execute(
            text("SELECT COUNT(*) FROM change_event_impacts WHERE context_feature_id = :feature_id"),
            {"feature_id": road_id},
        ).scalar_one()
        assert after_feature_delete == 0

        db_session.execute(delete(ChangeEvent).where(ChangeEvent.id == event_id))
        db_session.commit()

    with SessionLocal() as db_session:
        remaining = db_session.execute(text("SELECT COUNT(*) FROM change_event_impacts WHERE event_id = :event_id"), {"event_id": event_id}).scalar_one()
    assert remaining == 0


def test_impact_response_uses_spatial_terms_and_not_damage_claims(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)
    seed_context_features(monitor_id)

    response = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert response.status_code == 201
    payload = json.dumps(response.json()).lower()
    for forbidden in ["damaged", "destroyed", "blocked"]:
        assert forbidden not in payload


def test_impact_error_paths_and_validation(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_id = seed_event_graph(monitor_id)

    wrong_monitor = create_monitor_and_track(client, created_monitor_ids, name="Other Monitor")

    wrong_owner = client.post(f"/monitors/{wrong_monitor}/events/{event_id}/impact")
    assert wrong_owner.status_code == 404
    assert wrong_owner.json() == {"detail": "Change event not found"}

    invalid_uuid = client.post(f"/monitors/{monitor_id}/events/not-a-uuid/impact")
    assert invalid_uuid.status_code == 422

    missing_analysis = client.post(f"/monitors/{monitor_id}/analyses/{uuid4()}/impact")
    assert missing_analysis.status_code == 404

    no_context_bulk = client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/impact")
    assert no_context_bulk.status_code == 409


def test_impact_geometry_index_exists_and_intersection_srid_is_4326(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_id = seed_event_graph(monitor_id)
    seed_context_features(monitor_id)
    response = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert response.status_code == 201

    with SessionLocal() as db_session:
        index_names = db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'change_event_impacts' "
                "AND indexname = 'ix_change_event_impacts_intersection_geometry_gist'"
            )
        ).scalars().all()
        srids = db_session.execute(
            text(
                "SELECT DISTINCT ST_SRID(intersection_geometry) FROM change_event_impacts "
                "WHERE event_id = :event_id AND intersection_geometry IS NOT NULL"
            ),
            {"event_id": event_id},
        ).scalars().all()

    assert index_names == ["ix_change_event_impacts_intersection_geometry_gist"]
    assert srids == [4326]
