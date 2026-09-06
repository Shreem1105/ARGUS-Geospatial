from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.context import (
    FEATURE_TYPE_ADMINISTRATIVE,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_WATERWAY,
    ContextFeatureCandidate,
    ContextFetchResult,
    ContextProviderError,
    ContextProviderLimitExceededError,
    get_context_provider,
)
from app.main import app
from app.models import ContextFeature, Monitor
from app.db.session import SessionLocal

VALID_MONITOR_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.852, 35.221],
            [-80.847, 35.221],
            [-80.847, 35.226],
            [-80.852, 35.226],
            [-80.852, 35.221],
        ]
    ],
}


def build_monitor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Context Test Monitor",
        "description": "Monitor for context refresh tests",
        "geometry": deepcopy(VALID_MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 10.0,
    }
    payload.update(overrides)
    return payload


def _line_geometry() -> dict[str, object]:
    return {
        "type": "LineString",
        "coordinates": [
            [-80.8515, 35.2230],
            [-80.8475, 35.2230],
        ],
    }


def _building_geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-80.8514, 35.2220],
                [-80.8508, 35.2220],
                [-80.8508, 35.2226],
                [-80.8514, 35.2226],
                [-80.8514, 35.2220],
            ]
        ],
    }


def _waterway_geometry() -> dict[str, object]:
    return {
        "type": "LineString",
        "coordinates": [
            [-80.8513, 35.2247],
            [-80.8478, 35.2247],
        ],
    }


def _admin_geometry() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-80.8530, 35.2200],
                [-80.8460, 35.2200],
                [-80.8460, 35.2270],
                [-80.8530, 35.2270],
                [-80.8530, 35.2200],
            ]
        ],
    }


class FakeContextProvider:
    provider_name = "openstreetmap"
    attribution = "© OpenStreetMap contributors"

    def __init__(
        self,
        *,
        roads: list[ContextFeatureCandidate] | None = None,
        buildings: list[ContextFeatureCandidate] | None = None,
        waterways: list[ContextFeatureCandidate] | None = None,
        administrative: list[ContextFeatureCandidate] | None = None,
        raise_error: bool = False,
    ) -> None:
        self._roads = roads or []
        self._buildings = buildings or []
        self._waterways = waterways or []
        self._administrative = administrative or []
        self.raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def _result(
        self,
        *,
        feature_type: str,
        intersects_geometry: dict[str, object],
        max_features: int,
        features: list[ContextFeatureCandidate],
    ) -> ContextFetchResult:
        self.calls.append(
            {
                "feature_type": feature_type,
                "intersects_geometry": intersects_geometry,
                "max_features": max_features,
            }
        )
        if self.raise_error:
            raise ContextProviderError("provider unavailable")

        return ContextFetchResult(
            provider=self.provider_name,
            feature_type=feature_type,
            fetched_count=len(features),
            skipped_count=0,
            features=features,
        )

    def fetch_roads(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> ContextFetchResult:
        return self._result(
            feature_type=FEATURE_TYPE_ROAD,
            intersects_geometry=intersects_geometry,
            max_features=max_features,
            features=list(self._roads),
        )

    def fetch_buildings(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> ContextFetchResult:
        return self._result(
            feature_type=FEATURE_TYPE_BUILDING,
            intersects_geometry=intersects_geometry,
            max_features=max_features,
            features=list(self._buildings),
        )

    def fetch_waterways(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> ContextFetchResult:
        return self._result(
            feature_type=FEATURE_TYPE_WATERWAY,
            intersects_geometry=intersects_geometry,
            max_features=max_features,
            features=list(self._waterways),
        )

    def fetch_administrative_boundaries(
        self,
        *,
        intersects_geometry: dict[str, object],
        max_features: int,
    ) -> ContextFetchResult:
        return self._result(
            feature_type=FEATURE_TYPE_ADMINISTRATIVE,
            intersects_geometry=intersects_geometry,
            max_features=max_features,
            features=list(self._administrative),
        )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> Generator[list[UUID], None, None]:
    ids: list[UUID] = []
    yield ids

    if not ids:
        return

    with SessionLocal() as db_session:
        db_session.execute(delete(Monitor).where(Monitor.id.in_(ids)))
        db_session.commit()


@pytest.fixture(autouse=True)
def clear_provider_override() -> Generator[None, None, None]:
    app.dependency_overrides.pop(get_context_provider, None)
    yield
    app.dependency_overrides.pop(get_context_provider, None)


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> dict[str, object]:
    response = client.post("/monitors", json=build_monitor_payload(**overrides))
    assert response.status_code == 201
    body = response.json()
    created_monitor_ids.append(UUID(body["id"]))
    return body


def make_candidate(
    *,
    provider_feature_id: str,
    feature_type: str,
    geometry: dict[str, object],
    feature_subtype: str | None,
    name: str | None,
    properties: dict[str, object],
) -> ContextFeatureCandidate:
    return ContextFeatureCandidate(
        provider_feature_id=provider_feature_id,
        feature_type=feature_type,
        feature_subtype=feature_subtype,
        name=name,
        geometry=geometry,
        properties=properties,
        source_updated_at=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
    )


def make_full_provider() -> FakeContextProvider:
    return FakeContextProvider(
        roads=[
            make_candidate(
                provider_feature_id="way/101",
                feature_type=FEATURE_TYPE_ROAD,
                geometry=_line_geometry(),
                feature_subtype="primary",
                name="Main St",
                properties={"highway": "primary", "road_class": "primary", "lanes": "2"},
            )
        ],
        buildings=[
            make_candidate(
                provider_feature_id="way/201",
                feature_type=FEATURE_TYPE_BUILDING,
                geometry=_building_geometry(),
                feature_subtype="building",
                name="Library",
                properties={"building": "yes", "building_levels": "3", "amenity": "library"},
            )
        ],
        waterways=[
            make_candidate(
                provider_feature_id="way/301",
                feature_type=FEATURE_TYPE_WATERWAY,
                geometry=_waterway_geometry(),
                feature_subtype="stream",
                name="Creek",
                properties={"waterway": "stream", "intermittent": "no"},
            )
        ],
        administrative=[
            make_candidate(
                provider_feature_id="relation/401",
                feature_type=FEATURE_TYPE_ADMINISTRATIVE,
                geometry=_admin_geometry(),
                feature_subtype="city",
                name="Charlotte",
                properties={"boundary": "administrative", "admin_level": "8", "place": "city"},
            )
        ],
    )


def run_refresh(client: TestClient, monitor_id: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    response = client.post(f"/monitors/{monitor_id}/context/refresh", json=payload)
    assert response.status_code == 200
    return response.json()


def test_context_refresh_succeeds_and_returns_counts(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    body = run_refresh(client, monitor["id"])

    assert body["provider"] == "openstreetmap"
    assert body["fetched"] == 4
    assert body["inserted"] == 4
    assert body["updated"] == 0
    assert body["skipped"] == 0
    assert body["by_type"]["road"] == 1
    assert body["by_type"]["building"] == 1
    assert body["by_type"]["waterway"] == 1
    assert body["by_type"]["administrative"] == 1


def test_context_refresh_provider_called_with_monitor_geometry(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    run_refresh(client, monitor["id"])

    assert len(provider.calls) == 4
    for call in provider.calls:
        intersects_geometry = call["intersects_geometry"]
        assert isinstance(intersects_geometry, dict)
        assert intersects_geometry["type"] == "Polygon"
        assert call["max_features"] == 4000


def test_context_refresh_feature_type_subset_respected(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    body = run_refresh(
        client,
        monitor["id"],
        payload={"feature_types": ["road", "building"]},
    )

    called_types = {str(call["feature_type"]) for call in provider.calls}
    assert called_types == {"road", "building"}
    assert body["fetched"] == 2
    assert body["by_type"] == {
        "road": 1,
        "building": 1,
        "waterway": 0,
        "administrative": 0,
    }


def test_context_refresh_duplicate_run_is_idempotent(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    first = run_refresh(client, monitor["id"])
    second = run_refresh(client, monitor["id"])

    assert first["inserted"] == 4
    assert second["inserted"] == 0
    assert second["updated"] == 4

    with SessionLocal() as db_session:
        row_count = db_session.execute(
            text("SELECT COUNT(*) FROM context_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert row_count == 4


def test_context_refresh_updates_existing_properties(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    updated_provider = make_full_provider()
    updated_provider._roads[0].name = "Renamed Road"
    updated_provider._roads[0].properties["lanes"] = "4"
    app.dependency_overrides[get_context_provider] = lambda: updated_provider

    second = run_refresh(client, monitor["id"])
    assert second["inserted"] == 0
    assert second["updated"] >= 1

    with SessionLocal() as db_session:
        row = db_session.execute(
            text(
                "SELECT name, properties->>'lanes' AS lanes FROM context_features "
                "WHERE monitor_id = :monitor_id AND feature_type = 'road'"
            ),
            {"monitor_id": monitor["id"]},
        ).mappings().one()

    assert row["name"] == "Renamed Road"
    assert row["lanes"] == "4"


def test_context_refresh_skips_malformed_geometry(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    malformed = make_candidate(
        provider_feature_id="way/999",
        feature_type=FEATURE_TYPE_ROAD,
        geometry={"type": "LineString", "coordinates": "not-a-valid-linestring"},
        feature_subtype="service",
        name="Broken",
        properties={"highway": "service", "road_class": "service"},
    )
    provider = FakeContextProvider(roads=[malformed])
    app.dependency_overrides[get_context_provider] = lambda: provider

    body = run_refresh(client, monitor["id"], payload={"feature_types": ["road"]})

    assert body["fetched"] == 1
    assert body["inserted"] == 0
    assert body["skipped"] == 1


def test_context_refresh_provider_failure_returns_502(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeContextProvider(raise_error=True)
    app.dependency_overrides[get_context_provider] = lambda: provider

    response = client.post(f"/monitors/{monitor['id']}/context/refresh")

    assert response.status_code == 502
    assert response.json() == {"detail": "Context provider unavailable"}


def test_context_refresh_oversized_query_guard_returns_409(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import context_service

    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    monkeypatch.setattr(context_service, "MAX_CONTEXT_QUERY_AREA_KM2", 0.00001)

    response = client.post(f"/monitors/{monitor['id']}/context/refresh")

    assert response.status_code == 409
    assert "bulk-data workflow" in response.json()["detail"]
    assert provider.calls == []


def test_context_refresh_provider_limit_exceeded_returns_409(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    class LimitProvider(FakeContextProvider):
        def fetch_roads(self, *, intersects_geometry: dict[str, object], max_features: int) -> ContextFetchResult:
            raise ContextProviderLimitExceededError("too many features")

    app.dependency_overrides[get_context_provider] = lambda: LimitProvider()

    response = client.post(
        f"/monitors/{monitor['id']}/context/refresh",
        json={"feature_types": ["road"]},
    )

    assert response.status_code == 409
    assert "too many features" in response.json()["detail"] or "reduce AOI" in response.json()["detail"]


def test_context_refresh_persists_geometry_types_and_srid(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        rows = db_session.execute(
            text(
                "SELECT feature_type, GeometryType(geometry) AS geometry_type, ST_SRID(geometry) AS srid "
                "FROM context_features WHERE monitor_id = :monitor_id ORDER BY feature_type"
            ),
            {"monitor_id": monitor["id"]},
        ).mappings().all()

    assert len(rows) == 4
    row_map = {row["feature_type"]: row for row in rows}
    assert str(row_map["road"]["geometry_type"]).upper() in {"LINESTRING", "MULTILINESTRING"}
    assert str(row_map["building"]["geometry_type"]).upper() in {"POLYGON", "MULTIPOLYGON"}
    assert str(row_map["waterway"]["geometry_type"]).upper() in {"LINESTRING", "MULTILINESTRING", "POLYGON", "MULTIPOLYGON"}
    assert str(row_map["administrative"]["geometry_type"]).upper() in {"POLYGON", "MULTIPOLYGON"}

    for row in rows:
        assert int(row["srid"]) == 4326


def test_context_refresh_properties_stored_as_jsonb(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        value = db_session.execute(
            text(
                "SELECT jsonb_typeof(properties) FROM context_features "
                "WHERE monitor_id = :monitor_id LIMIT 1"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert value == "object"


def test_context_feature_unique_constraint_prevents_duplicates(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])
    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        duplicates = db_session.execute(
            text(
                "SELECT provider_feature_id, feature_type, COUNT(*) AS c "
                "FROM context_features WHERE monitor_id = :monitor_id "
                "GROUP BY provider_feature_id, feature_type HAVING COUNT(*) > 1"
            ),
            {"monitor_id": monitor["id"]},
        ).mappings().all()

    assert duplicates == []


def test_context_geometry_gist_index_exists() -> None:
    with SessionLocal() as db_session:
        indexes = db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'context_features' AND indexname = 'ix_context_features_geometry_gist'"
            )
        ).scalars().all()

    assert indexes == ["ix_context_features_geometry_gist"]


def test_context_list_endpoint_and_filters(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    all_response = client.get(f"/monitors/{monitor['id']}/context?limit=50&offset=0")
    type_response = client.get(f"/monitors/{monitor['id']}/context?feature_type=road")
    subtype_response = client.get(f"/monitors/{monitor['id']}/context?feature_subtype=primary")
    provider_response = client.get(f"/monitors/{monitor['id']}/context?provider=openstreetmap")

    assert all_response.status_code == 200
    assert len(all_response.json()) == 4

    assert type_response.status_code == 200
    assert len(type_response.json()) == 1
    assert type_response.json()[0]["feature_type"] == "road"

    assert subtype_response.status_code == 200
    assert len(subtype_response.json()) == 1
    assert subtype_response.json()[0]["feature_subtype"] == "primary"

    assert provider_response.status_code == 200
    assert len(provider_response.json()) == 4


def test_context_list_pagination(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    page = client.get(f"/monitors/{monitor['id']}/context?limit=2&offset=1")

    assert page.status_code == 200
    assert len(page.json()) == 2


def test_context_summary_aggregation(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    response = client.get(f"/monitors/{monitor['id']}/context/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_features"] == 4
    assert body["by_type"]["road"] == 1
    assert body["by_type"]["building"] == 1
    assert body["road_classes"]["primary"] == 1
    assert body["attribution"] == "© OpenStreetMap contributors"


def test_context_refresh_missing_monitor_returns_404(client: TestClient) -> None:
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    response = client.post(f"/monitors/{uuid4()}/context/refresh")

    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_context_list_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.get(f"/monitors/{uuid4()}/context")
    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_context_summary_missing_monitor_returns_404(client: TestClient) -> None:
    response = client.get(f"/monitors/{uuid4()}/context/summary")
    assert response.status_code == 404
    assert response.json() == {"detail": "Monitor not found"}


def test_context_refresh_rejects_invalid_feature_type(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    response = client.post(
        f"/monitors/{monitor['id']}/context/refresh",
        json={"feature_types": ["invalid-type"]},
    )

    assert response.status_code == 422


def test_context_list_returns_geojson_geometry(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor["id"])

    response = client.get(f"/monitors/{monitor['id']}/context?feature_type=road")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["geometry"]["type"] in {"LineString", "MultiLineString"}
    assert isinstance(item["geometry"]["coordinates"], list)


def test_monitor_delete_cascades_context_features(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = monitor["id"]

    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider
    run_refresh(client, monitor_id)

    delete_response = client.delete(f"/monitors/{monitor_id}")
    assert delete_response.status_code == 204

    created_monitor_ids.remove(UUID(monitor_id))

    with SessionLocal() as db_session:
        remaining = db_session.execute(
            text("SELECT COUNT(*) FROM context_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()

    assert remaining == 0


def test_context_refresh_absent_name_stored_as_null(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeContextProvider(
        roads=[
            make_candidate(
                provider_feature_id="way/909",
                feature_type=FEATURE_TYPE_ROAD,
                geometry=_line_geometry(),
                feature_subtype="service",
                name=None,
                properties={"highway": "service", "road_class": "service"},
            )
        ]
    )
    app.dependency_overrides[get_context_provider] = lambda: provider

    run_refresh(client, monitor["id"], payload={"feature_types": ["road"]})

    with SessionLocal() as db_session:
        name = db_session.execute(
            text(
                "SELECT name FROM context_features "
                "WHERE monitor_id = :monitor_id AND provider_feature_id = 'way/909'"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert name is None


def test_context_refresh_records_provider_attribution_in_properties(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        attribution = db_session.execute(
            text(
                "SELECT properties->>'provider_attribution' FROM context_features "
                "WHERE monitor_id = :monitor_id LIMIT 1"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert attribution == "© OpenStreetMap contributors"


def test_context_refresh_updates_fetched_timestamp_on_repeat(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = make_full_provider()
    app.dependency_overrides[get_context_provider] = lambda: provider

    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        first_fetched = db_session.execute(
            text(
                "SELECT fetched_at FROM context_features "
                "WHERE monitor_id = :monitor_id AND provider_feature_id = 'way/101'"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    run_refresh(client, monitor["id"])

    with SessionLocal() as db_session:
        second_fetched = db_session.execute(
            text(
                "SELECT fetched_at FROM context_features "
                "WHERE monitor_id = :monitor_id AND provider_feature_id = 'way/101'"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert second_fetched >= first_fetched


def test_context_refresh_respects_provider_feature_uniqueness_per_type(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    shared_id = f"way/{uuid4()}"

    provider = FakeContextProvider(
        roads=[
            make_candidate(
                provider_feature_id=shared_id,
                feature_type=FEATURE_TYPE_ROAD,
                geometry=_line_geometry(),
                feature_subtype="primary",
                name="Road One",
                properties={"highway": "primary", "road_class": "primary"},
            )
        ],
        waterways=[
            make_candidate(
                provider_feature_id=shared_id,
                feature_type=FEATURE_TYPE_WATERWAY,
                geometry=_waterway_geometry(),
                feature_subtype="stream",
                name="Water One",
                properties={"waterway": "stream"},
            )
        ],
    )
    app.dependency_overrides[get_context_provider] = lambda: provider

    body = run_refresh(client, monitor["id"], payload={"feature_types": ["road", "waterway"]})

    assert body["inserted"] == 2
    with SessionLocal() as db_session:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM context_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert count == 2


def test_context_refresh_normalizes_feature_subtype_to_lowercase(client: TestClient, created_monitor_ids: list[UUID]) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeContextProvider(
        roads=[
            make_candidate(
                provider_feature_id="way/777",
                feature_type=FEATURE_TYPE_ROAD,
                geometry=_line_geometry(),
                feature_subtype="Primary",
                name="Mixed Case",
                properties={"highway": "primary", "road_class": "primary"},
            )
        ]
    )
    app.dependency_overrides[get_context_provider] = lambda: provider

    run_refresh(client, monitor["id"], payload={"feature_types": ["road"]})

    response = client.get(f"/monitors/{monitor['id']}/context?feature_type=road")
    assert response.status_code == 200
    assert response.json()[0]["feature_subtype"] == "primary"

    with SessionLocal() as db_session:
        subtype = db_session.execute(
            text(
                "SELECT feature_subtype FROM context_features "
                "WHERE monitor_id = :monitor_id AND provider_feature_id = 'way/777'"
            ),
            {"monitor_id": monitor["id"]},
        ).scalar_one()

    assert subtype == "primary"


def test_context_refresh_allows_multiline_and_multipolygon_geometries(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    provider = FakeContextProvider(
        roads=[
            make_candidate(
                provider_feature_id="way/808",
                feature_type=FEATURE_TYPE_ROAD,
                geometry={
                    "type": "MultiLineString",
                    "coordinates": [
                        [[-80.8510, 35.2225], [-80.8500, 35.2225]],
                        [[-80.8500, 35.2225], [-80.8490, 35.2225]],
                    ],
                },
                feature_subtype="secondary",
                name="Segmented",
                properties={"highway": "secondary", "road_class": "secondary"},
            )
        ],
        buildings=[
            make_candidate(
                provider_feature_id="relation/909",
                feature_type=FEATURE_TYPE_BUILDING,
                geometry={
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[
                            [-80.8514, 35.2250],
                            [-80.8510, 35.2250],
                            [-80.8510, 35.2254],
                            [-80.8514, 35.2254],
                            [-80.8514, 35.2250],
                        ]],
                        [[
                            [-80.8508, 35.2250],
                            [-80.8504, 35.2250],
                            [-80.8504, 35.2254],
                            [-80.8508, 35.2254],
                            [-80.8508, 35.2250],
                        ]],
                    ],
                },
                feature_subtype="yes",
                name="Complex Building",
                properties={"building": "yes"},
            )
        ],
    )
    app.dependency_overrides[get_context_provider] = lambda: provider

    body = run_refresh(client, monitor["id"], payload={"feature_types": ["road", "building"]})
    assert body["inserted"] == 2

    with SessionLocal() as db_session:
        rows = db_session.execute(
            text(
                "SELECT feature_type, GeometryType(geometry) AS geometry_type FROM context_features "
                "WHERE monitor_id = :monitor_id ORDER BY feature_type"
            ),
            {"monitor_id": monitor["id"]},
        ).mappings().all()

    assert len(rows) == 2
    row_map = {row["feature_type"]: str(row["geometry_type"]).upper() for row in rows}
    assert row_map["road"] == "MULTILINESTRING"
    assert row_map["building"] == "MULTIPOLYGON"
