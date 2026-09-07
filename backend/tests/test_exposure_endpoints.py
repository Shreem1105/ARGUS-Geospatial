from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

import app.services.environment_service as environment_service
import app.services.population_service as population_service
from app.context import (
    EnvironmentalFeatureCandidate,
    EnvironmentalFetchResult,
    EnvironmentalProviderError,
    EnvironmentalProviderLimitExceededError,
    LandCoverClassBreakdown,
    LandCoverExposureResult,
    LandCoverProviderError,
    LandCoverSourceCandidate,
    PopulationFeatureCandidate,
    PopulationFetchResult,
    PopulationProviderError,
    PopulationProviderLimitExceededError,
    get_environmental_provider,
    get_land_cover_provider,
    get_population_provider,
)
from app.db.session import SessionLocal
from app.gis.conversion import geojson_geometry_to_wkb
from app.main import app
from app.models import (
    ChangeAnalysis,
    ChangeEvent,
    ChangeEventEnvironmentalExposure,
    ChangeEventPopulationExposure,
    ContextFeature,
    EnvironmentalFeature,
    Monitor,
    MonitorLandCoverSource,
    PopulationFeature,
    PreparedObservation,
    SatelliteObservation,
)

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
        "name": "Exposure Test Monitor",
        "description": "Monitor for exposure endpoint tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 10.0,
    }
    payload.update(overrides)
    return payload


def _population_geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[-80.8514, 35.2219], [-80.8491, 35.2219], [-80.8491, 35.2238], [-80.8514, 35.2238], [-80.8514, 35.2219]]],
    }


def _environment_intersect_geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[-80.8509, 35.2221], [-80.8497, 35.2221], [-80.8497, 35.2233], [-80.8509, 35.2233], [-80.8509, 35.2221]]],
    }


def _environment_near_geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[-80.8512, 35.22335], [-80.8504, 35.22335], [-80.8504, 35.2240], [-80.8512, 35.2240], [-80.8512, 35.22335]]],
    }


class FakePopulationProvider:
    provider_name = "us_census"
    attribution = "Source: U.S. Census Bureau"

    def __init__(
        self,
        *,
        features: list[PopulationFeatureCandidate] | None = None,
        dataset_version: str = "acs5_2024",
        raise_error: bool = False,
        raise_limit_error: bool = False,
    ) -> None:
        self._features = features or []
        self.dataset_version = dataset_version
        self.raise_error = raise_error
        self.raise_limit_error = raise_limit_error
        self.calls: list[dict[str, object]] = []

    def fetch_population_units(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> PopulationFetchResult:
        self.calls.append(
            {
                "intersects_geometry": intersects_geometry,
                "max_features": max_features,
            }
        )

        if self.raise_limit_error:
            raise PopulationProviderLimitExceededError("too many")
        if self.raise_error:
            raise PopulationProviderError("provider unavailable")

        return PopulationFetchResult(
            provider=self.provider_name,
            dataset="acs5_total_population_block_group",
            dataset_version=self.dataset_version,
            attribution=self.attribution,
            geography_type="block_group",
            fetched_count=len(self._features),
            skipped_count=0,
            features=list(self._features),
        )


class FakeLandCoverProvider:
    provider_name = "planetary_computer"
    attribution = "Contains modified Copernicus Sentinel data (2021+)"

    def __init__(
        self,
        *,
        dataset: str = "esa-worldcover",
        dataset_version: str = "v200",
        raise_fetch_error: bool = False,
        raise_compute_error: bool = False,
    ) -> None:
        self.dataset = dataset
        self.dataset_version = dataset_version
        self.raise_fetch_error = raise_fetch_error
        self.raise_compute_error = raise_compute_error
        self.fetch_calls: list[dict[str, object]] = []
        self.compute_calls: list[dict[str, object]] = []

    def fetch_land_cover_source(
        self,
        *,
        intersects_geometry: dict[str, object],
    ) -> LandCoverSourceCandidate:
        self.fetch_calls.append({"intersects_geometry": intersects_geometry})
        if self.raise_fetch_error:
            raise LandCoverProviderError("provider unavailable")

        return LandCoverSourceCandidate(
            provider=self.provider_name,
            dataset=self.dataset,
            dataset_version=self.dataset_version,
            source_item_id=f"ESA-WC-{self.dataset_version}",
            asset_key="map",
            asset_href="https://example.test/worldcover.tif",
            asset_media_type="image/tiff; application=geotiff",
            properties={"collection": self.dataset},
            source_updated_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        )

    def compute_land_cover_exposure(
        self,
        *,
        event_geometry: dict[str, object],
        event_area_m2: float,
        source: LandCoverSourceCandidate,
    ) -> LandCoverExposureResult:
        self.compute_calls.append(
            {
                "event_geometry": event_geometry,
                "event_area_m2": event_area_m2,
                "source_item_id": source.source_item_id,
            }
        )
        if self.raise_compute_error:
            raise LandCoverProviderError("compute failed")

        return LandCoverExposureResult(
            provider=source.provider,
            dataset=source.dataset,
            dataset_version=source.dataset_version,
            classes=[
                LandCoverClassBreakdown(
                    class_code=50,
                    class_name="built_up",
                    area_m2=event_area_m2 * 0.6,
                    fraction_of_event=0.6,
                    properties={"pixel_count": 60, "nodata_fraction": 0.1},
                ),
                LandCoverClassBreakdown(
                    class_code=80,
                    class_name="permanent_water_bodies",
                    area_m2=event_area_m2 * 0.3,
                    fraction_of_event=0.3,
                    properties={"pixel_count": 30, "nodata_fraction": 0.1},
                ),
            ],
            nodata_fraction=0.1,
            total_pixels=100,
            valid_pixels=90,
        )


class FakeEnvironmentalProvider:
    provider_name = "openstreetmap"
    dataset = "osm_environmental_features"
    attribution = "© OpenStreetMap contributors"

    def __init__(
        self,
        *,
        features: list[EnvironmentalFeatureCandidate] | None = None,
        dataset_version: str = "2026-09-05",
        raise_error: bool = False,
        raise_limit_error: bool = False,
    ) -> None:
        self._features = features or []
        self.dataset_version = dataset_version
        self.raise_error = raise_error
        self.raise_limit_error = raise_limit_error
        self.calls: list[dict[str, object]] = []

    def fetch_protected_areas(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> EnvironmentalFetchResult:
        self.calls.append(
            {
                "intersects_geometry": intersects_geometry,
                "max_features": max_features,
            }
        )
        if self.raise_limit_error:
            raise EnvironmentalProviderLimitExceededError("too many")
        if self.raise_error:
            raise EnvironmentalProviderError("provider unavailable")

        return EnvironmentalFetchResult(
            provider=self.provider_name,
            dataset=self.dataset,
            dataset_version=self.dataset_version,
            attribution=self.attribution,
            fetched_count=len(self._features),
            skipped_count=0,
            features=list(self._features),
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


@pytest.fixture(autouse=True)
def clear_provider_overrides() -> Generator[None, None, None]:
    app.dependency_overrides.pop(get_population_provider, None)
    app.dependency_overrides.pop(get_land_cover_provider, None)
    app.dependency_overrides.pop(get_environmental_provider, None)
    yield
    app.dependency_overrides.pop(get_population_provider, None)
    app.dependency_overrides.pop(get_land_cover_provider, None)
    app.dependency_overrides.pop(get_environmental_provider, None)


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> UUID:
    response = client.post("/monitors", json=build_monitor_payload(**overrides))
    assert response.status_code == 201
    monitor_id = UUID(response.json()["id"])
    created_monitor_ids.append(monitor_id)
    return monitor_id


def seed_event_graph(monitor_id: UUID, *, event_count: int = 1, severity: str = "medium") -> tuple[UUID, list[UUID]]:
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

        event_ids: list[UUID] = []
        for index in range(event_count):
            if index == 0:
                geometry = EVENT_POLYGON
            else:
                geometry = {
                    "type": "Polygon",
                    "coordinates": [[[-80.8502, 35.2234], [-80.8492, 35.2234], [-80.8492, 35.2242], [-80.8502, 35.2242], [-80.8502, 35.2234]]],
                }

            event = ChangeEvent(
                monitor_id=monitor_id,
                analysis_id=analysis.id,
                geometry=geojson_geometry_to_wkb(geometry),
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
            db_session.flush()
            event_ids.append(event.id)

        db_session.commit()
        return analysis.id, event_ids


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
        provider_feature_id="way/building-intersect",
        feature_type="building",
        feature_subtype="building",
        geometry={"type": "Polygon", "coordinates": [[[-80.8504, 35.2226], [-80.8499, 35.2226], [-80.8499, 35.22305], [-80.8504, 35.22305], [-80.8504, 35.2226]]]},
        name="Intersecting Building",
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
        provider_feature_id="relation/admin-city",
        feature_type="administrative",
        feature_subtype="city",
        geometry={"type": "Polygon", "coordinates": [[[-80.8530, 35.2200], [-80.8460, 35.2200], [-80.8460, 35.2270], [-80.8530, 35.2270], [-80.8530, 35.2200]]]},
        name="Charlotte",
        properties={"admin_level": "8", "boundary": "administrative", "place": "city"},
    )


def make_population_candidates(*, population: int = 1200, source_feature_id: str = "bg-370670001001") -> list[PopulationFeatureCandidate]:
    return [
        PopulationFeatureCandidate(
            source_feature_id=source_feature_id,
            geography_type="block_group",
            name="Block Group 1",
            population=population,
            geometry=_population_geometry(),
            properties={"geoid": source_feature_id, "county_fips": "119", "state_fips": "37"},
            source_updated_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        )
    ]


def make_environment_candidates(*, suffix: str = "base") -> list[EnvironmentalFeatureCandidate]:
    return [
        EnvironmentalFeatureCandidate(
            source_feature_id=f"relation/protected-{suffix}",
            feature_type="protected_area",
            feature_subtype="national_park",
            name=f"Protected Area {suffix}",
            designation="national_park",
            manager="NPS",
            geometry=_environment_intersect_geometry(),
            properties={"boundary": "national_park", "protect_class": "2"},
            source_updated_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        ),
        EnvironmentalFeatureCandidate(
            source_feature_id=f"relation/wetland-{suffix}",
            feature_type="wetland",
            feature_subtype="wetland",
            name=f"Wetland {suffix}",
            designation="wetland",
            manager=None,
            geometry=_environment_near_geometry(),
            properties={"natural": "wetland"},
            source_updated_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        ),
    ]


def _refresh_all_datasets(
    client: TestClient,
    *,
    monitor_id: UUID,
    population_provider: FakePopulationProvider,
    land_cover_provider: FakeLandCoverProvider,
    environment_provider: FakeEnvironmentalProvider,
) -> None:
    app.dependency_overrides[get_population_provider] = lambda: population_provider
    app.dependency_overrides[get_land_cover_provider] = lambda: land_cover_provider
    app.dependency_overrides[get_environmental_provider] = lambda: environment_provider

    population_response = client.post(f"/monitors/{monitor_id}/population/refresh")
    assert population_response.status_code == 200

    land_cover_response = client.post(f"/monitors/{monitor_id}/land-cover/refresh")
    assert land_cover_response.status_code == 200

    environment_response = client.post(f"/monitors/{monitor_id}/environment/refresh")
    assert environment_response.status_code == 200


def test_population_refresh_success_and_provider_called_with_monitor_geometry(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    provider = FakePopulationProvider(features=make_population_candidates())
    app.dependency_overrides[get_population_provider] = lambda: provider

    response = client.post(f"/monitors/{monitor_id}/population/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "us_census"
    assert payload["dataset"] == "acs5_total_population_block_group"
    assert payload["fetched"] == 1
    assert payload["inserted"] == 1
    assert provider.calls
    assert provider.calls[0]["intersects_geometry"]["type"] == "Polygon"

    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM population_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()
        srid = db_session.execute(
            text("SELECT ST_SRID(geometry) FROM population_features WHERE monitor_id = :monitor_id LIMIT 1"),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert count == 1
    assert srid == 4326


def test_population_refresh_missing_monitor_returns_404(client: TestClient) -> None:
    provider = FakePopulationProvider(features=make_population_candidates())
    app.dependency_overrides[get_population_provider] = lambda: provider

    response = client.post(f"/monitors/{uuid4()}/population/refresh")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_population_refresh_provider_failure_returns_502(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    provider = FakePopulationProvider(raise_error=True)
    app.dependency_overrides[get_population_provider] = lambda: provider

    response = client.post(f"/monitors/{monitor_id}/population/refresh")

    assert response.status_code == 502
    assert response.json() == {"detail": "Population provider unavailable"}


def test_population_refresh_limit_guard_returns_409(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    provider = FakePopulationProvider(features=make_population_candidates())
    app.dependency_overrides[get_population_provider] = lambda: provider
    monkeypatch.setattr(population_service, "MAX_POPULATION_QUERY_AREA_KM2", 0.000001)

    response = client.post(f"/monitors/{monitor_id}/population/refresh")

    assert response.status_code == 409
    assert "too large" in response.json()["detail"].lower()


def test_population_refresh_is_idempotent_upsert(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)

    first_provider = FakePopulationProvider(
        features=make_population_candidates(population=1200, source_feature_id="bg-370670001001")
    )
    app.dependency_overrides[get_population_provider] = lambda: first_provider
    first_response = client.post(f"/monitors/{monitor_id}/population/refresh")
    assert first_response.status_code == 200
    assert first_response.json()["inserted"] == 1

    second_provider = FakePopulationProvider(
        features=make_population_candidates(population=1400, source_feature_id="bg-370670001001")
    )
    app.dependency_overrides[get_population_provider] = lambda: second_provider
    second_response = client.post(f"/monitors/{monitor_id}/population/refresh")

    assert second_response.status_code == 200
    assert second_response.json()["inserted"] == 0
    assert second_response.json()["updated"] == 1

    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM population_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()
        population = db_session.execute(
            text(
                "SELECT population FROM population_features "
                "WHERE monitor_id = :monitor_id AND source_feature_id = 'bg-370670001001'"
            ),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert count == 1
    assert population == 1400


def test_land_cover_refresh_success_and_upsert(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)

    first_provider = FakeLandCoverProvider(dataset_version="v100")
    app.dependency_overrides[get_land_cover_provider] = lambda: first_provider
    first_response = client.post(f"/monitors/{monitor_id}/land-cover/refresh")
    assert first_response.status_code == 200
    assert first_response.json()["inserted"] == 1

    second_provider = FakeLandCoverProvider(dataset_version="v200")
    app.dependency_overrides[get_land_cover_provider] = lambda: second_provider
    second_response = client.post(f"/monitors/{monitor_id}/land-cover/refresh")

    assert second_response.status_code == 200
    assert second_response.json()["inserted"] == 0
    assert second_response.json()["updated"] == 1
    assert second_provider.fetch_calls

    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM monitor_land_cover_sources WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()
        dataset_version = db_session.execute(
            text(
                "SELECT dataset_version FROM monitor_land_cover_sources "
                "WHERE monitor_id = :monitor_id LIMIT 1"
            ),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert count == 1
    assert dataset_version == "v200"


def test_land_cover_refresh_missing_monitor_and_provider_error(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    provider = FakeLandCoverProvider()
    app.dependency_overrides[get_land_cover_provider] = lambda: provider
    missing = client.post(f"/monitors/{uuid4()}/land-cover/refresh")
    assert missing.status_code == 404

    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    failing_provider = FakeLandCoverProvider(raise_fetch_error=True)
    app.dependency_overrides[get_land_cover_provider] = lambda: failing_provider
    failed = client.post(f"/monitors/{monitor_id}/land-cover/refresh")

    assert failed.status_code == 502
    assert failed.json() == {"detail": "Land-cover provider unavailable"}


def test_environment_refresh_success_and_idempotent_upsert(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)

    first_provider = FakeEnvironmentalProvider(features=make_environment_candidates(suffix="a"), dataset_version="2026-09-05")
    app.dependency_overrides[get_environmental_provider] = lambda: first_provider
    first_response = client.post(f"/monitors/{monitor_id}/environment/refresh")
    assert first_response.status_code == 200
    assert first_response.json()["inserted"] == 2

    second_provider = FakeEnvironmentalProvider(features=make_environment_candidates(suffix="a"), dataset_version="2026-09-06")
    app.dependency_overrides[get_environmental_provider] = lambda: second_provider
    second_response = client.post(f"/monitors/{monitor_id}/environment/refresh")

    assert second_response.status_code == 200
    assert second_response.json()["inserted"] == 0
    assert second_response.json()["updated"] == 2
    assert second_provider.calls

    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM environmental_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()
        srid = db_session.execute(
            text("SELECT ST_SRID(geometry) FROM environmental_features WHERE monitor_id = :monitor_id LIMIT 1"),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert count == 2
    assert srid == 4326


def test_environment_refresh_failure_paths(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)

    oversized_provider = FakeEnvironmentalProvider(features=make_environment_candidates())
    app.dependency_overrides[get_environmental_provider] = lambda: oversized_provider
    monkeypatch.setattr(environment_service, "MAX_ENVIRONMENT_QUERY_AREA_KM2", 0.000001)
    oversized = client.post(f"/monitors/{monitor_id}/environment/refresh")
    assert oversized.status_code == 409

    monkeypatch.setattr(environment_service, "MAX_ENVIRONMENT_QUERY_AREA_KM2", 750.0)

    failing_provider = FakeEnvironmentalProvider(raise_error=True)
    app.dependency_overrides[get_environmental_provider] = lambda: failing_provider
    failed = client.post(f"/monitors/{monitor_id}/environment/refresh")
    assert failed.status_code == 502

    missing_provider = FakeEnvironmentalProvider(features=make_environment_candidates())
    app.dependency_overrides[get_environmental_provider] = lambda: missing_provider
    missing = client.post(f"/monitors/{uuid4()}/environment/refresh")
    assert missing.status_code == 404


def test_compute_event_exposure_requires_all_datasets(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    provider = FakeLandCoverProvider()
    app.dependency_overrides[get_land_cover_provider] = lambda: provider

    response = client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure")

    assert response.status_code == 409
    assert "required datasets" in response.json()["detail"].lower()


def test_compute_event_exposure_and_get_exposure(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id, severity="high")
    event_id = event_ids[0]

    seed_context_features(monitor_id)
    population_provider = FakePopulationProvider(features=make_population_candidates())
    land_cover_provider = FakeLandCoverProvider()
    environment_provider = FakeEnvironmentalProvider(features=make_environment_candidates())
    _refresh_all_datasets(
        client,
        monitor_id=monitor_id,
        population_provider=population_provider,
        land_cover_provider=land_cover_provider,
        environment_provider=environment_provider,
    )

    impact_response = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
    assert impact_response.status_code == 201

    compute_response = client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure")

    assert compute_response.status_code == 201
    payload = compute_response.json()
    assert payload["computed"] is True
    assert payload["summary"]["scientific_severity"] == "high"
    assert payload["summary"]["population"]["estimated_exposed_population"] > 0
    assert payload["summary"]["land_cover"]["dominant_class"] == "built_up"
    assert payload["summary"]["environment"]["intersecting_count"] >= 1
    assert payload["summary"]["exposure_significance"] in {"low", "medium", "high"}
    assert land_cover_provider.compute_calls

    get_response = client.get(f"/monitors/{monitor_id}/events/{event_id}/exposure")
    assert get_response.status_code == 200
    assert get_response.json()["event_id"] == str(event_id)


def test_compute_event_exposure_idempotent_and_no_duplicates(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    seed_context_features(monitor_id)
    _refresh_all_datasets(
        client,
        monitor_id=monitor_id,
        population_provider=FakePopulationProvider(features=make_population_candidates()),
        land_cover_provider=FakeLandCoverProvider(),
        environment_provider=FakeEnvironmentalProvider(features=make_environment_candidates()),
    )

    assert client.post(f"/monitors/{monitor_id}/events/{event_id}/impact").status_code == 201

    first = client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure")
    second = client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["computed"] is False

    with SessionLocal() as db_session:
        duplicates = db_session.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "SELECT event_id, population_feature_id, COUNT(*) AS c "
                "FROM change_event_population_exposures "
                "WHERE event_id = :event_id "
                "GROUP BY event_id, population_feature_id HAVING COUNT(*) > 1"
                ") d"
            ),
            {"event_id": event_id},
        ).scalar_one()

    assert duplicates == 0


def test_compute_event_exposure_error_paths(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    invalid = client.post(f"/monitors/{monitor_id}/events/not-a-uuid/exposure")
    assert invalid.status_code == 422

    missing = client.post(f"/monitors/{monitor_id}/events/{uuid4()}/exposure")
    assert missing.status_code == 404

    other_monitor = create_monitor_and_track(client, created_monitor_ids, name="Other")
    wrong_owner = client.post(f"/monitors/{other_monitor}/events/{event_id}/exposure")
    assert wrong_owner.status_code == 404


def test_event_intelligence_requires_impact_and_exposure(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    seed_context_features(monitor_id)
    _refresh_all_datasets(
        client,
        monitor_id=monitor_id,
        population_provider=FakePopulationProvider(features=make_population_candidates()),
        land_cover_provider=FakeLandCoverProvider(),
        environment_provider=FakeEnvironmentalProvider(features=make_environment_candidates()),
    )

    no_impact = client.get(f"/monitors/{monitor_id}/events/{event_id}/intelligence")
    assert no_impact.status_code == 409
    assert "impact" in no_impact.json()["detail"].lower()

    assert client.post(f"/monitors/{monitor_id}/events/{event_id}/impact").status_code == 201

    no_exposure = client.get(f"/monitors/{monitor_id}/events/{event_id}/intelligence")
    assert no_exposure.status_code == 409
    assert "exposure" in no_exposure.json()["detail"].lower()

    assert client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure").status_code == 201

    intelligence = client.get(f"/monitors/{monitor_id}/events/{event_id}/intelligence")
    assert intelligence.status_code == 200
    body = intelligence.json()
    assert body["scientific_severity"] == "medium"
    assert body["context_significance"] in {"low", "medium", "high"}
    assert body["exposure_significance"] in {"low", "medium", "high"}


def test_bulk_analysis_exposure_and_summary_and_datasets(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    analysis_id, event_ids = seed_event_graph(monitor_id, event_count=2)
    seed_context_features(monitor_id)

    _refresh_all_datasets(
        client,
        monitor_id=monitor_id,
        population_provider=FakePopulationProvider(features=make_population_candidates()),
        land_cover_provider=FakeLandCoverProvider(),
        environment_provider=FakeEnvironmentalProvider(features=make_environment_candidates()),
    )

    for event_id in event_ids:
        response = client.post(f"/monitors/{monitor_id}/events/{event_id}/impact")
        assert response.status_code in {200, 201}

    first = client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/exposure")
    second = client.post(f"/monitors/{monitor_id}/analyses/{analysis_id}/exposure")

    assert first.status_code == 200
    first_body = first.json()
    assert first_body["event_count"] == 2
    assert first_body["computed"] == 2
    assert first_body["failed"] == 0

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["event_count"] == 2
    assert second_body["reused"] == 2

    summary = client.get(f"/monitors/{monitor_id}/exposure/summary")
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["events_with_population_exposure"] == 2
    assert summary_body["events_intersecting_protected_areas"] >= 1
    assert "built_up" in summary_body["events_by_dominant_land_cover"]

    datasets = client.get(f"/monitors/{monitor_id}/datasets")
    assert datasets.status_code == 200
    entries = {item["category"]: item for item in datasets.json()["datasets"]}
    assert entries["context"]["status"] == "available"
    assert entries["population"]["status"] == "available"
    assert entries["land_cover"]["status"] == "available"
    assert entries["environment"]["status"] == "available"


def test_population_feature_constraints_and_uniqueness(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)

    with SessionLocal() as db_session:
        feature = PopulationFeature(
            monitor_id=monitor_id,
            provider="us_census",
            dataset="acs5_total_population_block_group",
            dataset_version="acs5_2024",
            source_feature_id="bg-unique-1",
            geography_type="block_group",
            name="Block Group",
            population=100,
            geometry=geojson_geometry_to_wkb(_population_geometry()),
            properties={"geoid": "bg-unique-1"},
        )
        db_session.add(feature)
        db_session.commit()

        duplicate = PopulationFeature(
            monitor_id=monitor_id,
            provider="us_census",
            dataset="acs5_total_population_block_group",
            dataset_version="acs5_2024",
            source_feature_id="bg-unique-1",
            geography_type="block_group",
            name="Block Group",
            population=120,
            geometry=geojson_geometry_to_wkb(_population_geometry()),
            properties={"geoid": "bg-unique-1"},
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        invalid = PopulationFeature(
            monitor_id=monitor_id,
            provider="us_census",
            dataset="acs5_total_population_block_group",
            dataset_version="acs5_2024",
            source_feature_id="bg-negative-1",
            geography_type="block_group",
            name="Negative",
            population=-1,
            geometry=geojson_geometry_to_wkb(_population_geometry()),
            properties={"geoid": "bg-negative-1"},
        )
        db_session.add(invalid)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_environmental_feature_constraints_and_exposure_uniqueness(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    with SessionLocal() as db_session:
        feature = EnvironmentalFeature(
            monitor_id=monitor_id,
            provider="openstreetmap",
            dataset="osm_environmental_features",
            dataset_version="2026-09-05",
            source_feature_id="relation/protected-db",
            feature_type="protected_area",
            feature_subtype="national_park",
            name="Protected",
            designation="national_park",
            manager="NPS",
            geometry=geojson_geometry_to_wkb(_environment_intersect_geometry()),
            properties={"boundary": "protected_area"},
        )
        db_session.add(feature)
        db_session.flush()

        valid_exposure = ChangeEventEnvironmentalExposure(
            event_id=event_id,
            environmental_feature_id=feature.id,
            relationship_type="intersects",
            intersection_area_m2=10.0,
            intersection_fraction_of_event=0.1,
            distance_m=0.0,
            properties={"provider": "openstreetmap"},
        )
        db_session.add(valid_exposure)
        db_session.commit()

        duplicate = ChangeEventEnvironmentalExposure(
            event_id=event_id,
            environmental_feature_id=feature.id,
            relationship_type="intersects",
            intersection_area_m2=5.0,
            intersection_fraction_of_event=0.05,
            distance_m=0.0,
            properties={"provider": "openstreetmap"},
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        invalid = ChangeEventEnvironmentalExposure(
            event_id=event_id,
            environmental_feature_id=feature.id,
            relationship_type="unsupported",
            intersection_area_m2=1.0,
            intersection_fraction_of_event=0.01,
            distance_m=0.0,
            properties={"provider": "openstreetmap"},
        )
        db_session.add(invalid)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_population_exposure_constraints(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    with SessionLocal() as db_session:
        feature = PopulationFeature(
            monitor_id=monitor_id,
            provider="us_census",
            dataset="acs5_total_population_block_group",
            dataset_version="acs5_2024",
            source_feature_id="bg-for-exposure",
            geography_type="block_group",
            name="Block Group",
            population=300,
            geometry=geojson_geometry_to_wkb(_population_geometry()),
            properties={"geoid": "bg-for-exposure"},
        )
        db_session.add(feature)
        db_session.flush()

        valid = ChangeEventPopulationExposure(
            event_id=event_id,
            population_feature_id=feature.id,
            intersection_area_m2=10.0,
            source_area_m2=100.0,
            intersection_fraction=0.1,
            source_population=300,
            estimated_exposed_population=30.0,
            properties={"method": "areal_weighting"},
        )
        db_session.add(valid)
        db_session.commit()

        duplicate = ChangeEventPopulationExposure(
            event_id=event_id,
            population_feature_id=feature.id,
            intersection_area_m2=12.0,
            source_area_m2=100.0,
            intersection_fraction=0.12,
            source_population=300,
            estimated_exposed_population=36.0,
            properties={"method": "areal_weighting"},
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        invalid = ChangeEventPopulationExposure(
            event_id=event_id,
            population_feature_id=feature.id,
            intersection_area_m2=-1.0,
            source_area_m2=100.0,
            intersection_fraction=0.1,
            source_population=300,
            estimated_exposed_population=30.0,
            properties={"method": "areal_weighting"},
        )
        db_session.add(invalid)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_monitor_delete_cascades_population_land_cover_environment_and_exposures(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor_id = create_monitor_and_track(client, created_monitor_ids)
    _, event_ids = seed_event_graph(monitor_id)
    event_id = event_ids[0]

    seed_context_features(monitor_id)
    _refresh_all_datasets(
        client,
        monitor_id=monitor_id,
        population_provider=FakePopulationProvider(features=make_population_candidates()),
        land_cover_provider=FakeLandCoverProvider(),
        environment_provider=FakeEnvironmentalProvider(features=make_environment_candidates()),
    )

    assert client.post(f"/monitors/{monitor_id}/events/{event_id}/impact").status_code == 201
    assert client.post(f"/monitors/{monitor_id}/events/{event_id}/exposure").status_code == 201

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204
    created_monitor_ids.remove(monitor_id)

    with SessionLocal() as db_session:
        counts = {
            "population_features": db_session.execute(
                text("SELECT COUNT(*) FROM population_features WHERE monitor_id = :monitor_id"),
                {"monitor_id": monitor_id},
            ).scalar_one(),
            "monitor_land_cover_sources": db_session.execute(
                text("SELECT COUNT(*) FROM monitor_land_cover_sources WHERE monitor_id = :monitor_id"),
                {"monitor_id": monitor_id},
            ).scalar_one(),
            "environmental_features": db_session.execute(
                text("SELECT COUNT(*) FROM environmental_features WHERE monitor_id = :monitor_id"),
                {"monitor_id": monitor_id},
            ).scalar_one(),
            "change_event_population_exposures": db_session.execute(
                text(
                    "SELECT COUNT(*) FROM change_event_population_exposures "
                    "WHERE event_id IN (SELECT id FROM change_events WHERE monitor_id = :monitor_id)"
                ),
                {"monitor_id": monitor_id},
            ).scalar_one(),
            "change_event_environmental_exposures": db_session.execute(
                text(
                    "SELECT COUNT(*) FROM change_event_environmental_exposures "
                    "WHERE event_id IN (SELECT id FROM change_events WHERE monitor_id = :monitor_id)"
                ),
                {"monitor_id": monitor_id},
            ).scalar_one(),
        }

    assert counts["population_features"] == 0
    assert counts["monitor_land_cover_sources"] == 0
    assert counts["environmental_features"] == 0
    assert counts["change_event_population_exposures"] == 0
    assert counts["change_event_environmental_exposures"] == 0


def test_health_and_ready_endpoints_still_work(client: TestClient) -> None:
    root = client.get("/")
    health = client.get("/health")
    ready = client.get("/ready")

    assert root.status_code == 200
    assert root.json()["name"] == "ARGUS API"
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
