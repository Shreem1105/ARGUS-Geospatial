from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.main import app
from app.models import AnalysisJob, Monitor, UsageEvent, User, UserQuota
from app.schemas.jobs import MonitorRunEnqueueResponse
from app.services.quota_service import (
    USAGE_MANUAL_RUN,
    USAGE_OBSERVATION_SEARCH,
    USAGE_SEMANTIC_ANALYSIS,
    get_effective_quota_limits,
)


DEFAULT_PASSWORD = "QuotaPass!234"
VALID_POLYGON = {
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

LARGER_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-81.10, 35.00],
            [-80.40, 35.00],
            [-80.40, 35.60],
            [-81.10, 35.60],
            [-81.10, 35.00],
        ]
    ],
}


def _new_email() -> str:
    return f"quota-{uuid4().hex}@example.com"


def _register(client: TestClient, *, email: str) -> UUID:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "display_name": "Quota User"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["user"]["id"])


def _create_monitor(client: TestClient, *, name: str = "Quota Monitor") -> UUID:
    response = client.post(
        "/monitors",
        json={
            "name": name,
            "description": "Quota test monitor",
            "geometry": VALID_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 15,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _set_quota(
    *,
    user_id: UUID,
    max_monitors: int | None = None,
    max_active_monitors: int | None = None,
    max_aoi_area_km2: float | None = None,
    max_manual_runs_per_day: int | None = None,
    max_observation_searches_per_day: int | None = None,
    max_semantic_runs_per_day: int | None = None,
    max_concurrent_jobs: int | None = None,
) -> None:
    with SessionLocal() as db_session:
        quota = db_session.execute(select(UserQuota).where(UserQuota.user_id == user_id)).scalar_one_or_none()
        if quota is None:
            quota = UserQuota(user_id=user_id)

        quota.max_monitors = max_monitors
        quota.max_active_monitors = max_active_monitors
        quota.max_aoi_area_km2 = max_aoi_area_km2
        quota.max_manual_runs_per_day = max_manual_runs_per_day
        quota.max_observation_searches_per_day = max_observation_searches_per_day
        quota.max_semantic_runs_per_day = max_semantic_runs_per_day
        quota.max_concurrent_jobs = max_concurrent_jobs

        db_session.add(quota)
        db_session.commit()


def _insert_usage(*, user_id: UUID, usage_type: str, quantity: int = 1, created_at: datetime | None = None) -> None:
    with SessionLocal() as db_session:
        event = UsageEvent(
            user_id=user_id,
            usage_type=usage_type,
            resource_id=None,
            quantity=quantity,
            metadata_={"test": True},
        )
        if created_at is not None:
            event.created_at = created_at
        db_session.add(event)
        db_session.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def cleanup_users_and_monitors() -> Generator[dict[str, list[UUID]], None, None]:
    tracker = {"users": [], "monitors": []}
    yield tracker

    with SessionLocal() as db_session:
        if tracker["monitors"]:
            db_session.execute(delete(Monitor).where(Monitor.id.in_(tracker["monitors"])))
        if tracker["users"]:
            db_session.execute(delete(User).where(User.id.in_(tracker["users"])))
        db_session.commit()


def test_max_monitors_quota_blocks_additional_monitor(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
) -> None:
    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    _set_quota(user_id=user_id, max_monitors=1, max_active_monitors=10, max_aoi_area_km2=2000)

    first_monitor = _create_monitor(client, name="Quota One")
    cleanup_users_and_monitors["monitors"].append(first_monitor)

    second = client.post(
        "/monitors",
        json={
            "name": "Quota Two",
            "description": "should be blocked",
            "geometry": VALID_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 10,
        },
    )

    assert second.status_code == 429
    detail = second.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["quota"] == "max_monitors"


def test_max_active_monitors_quota_blocks_when_active_limit_reached(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
) -> None:
    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    _set_quota(user_id=user_id, max_monitors=10, max_active_monitors=1, max_aoi_area_km2=2000)

    first_monitor = _create_monitor(client, name="Active Limit Seed")
    cleanup_users_and_monitors["monitors"].append(first_monitor)

    blocked = client.post(
        "/monitors",
        json={
            "name": "Blocked by active quota",
            "description": "active limit should block",
            "geometry": VALID_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.6,
            "minimum_change_area_m2": 12,
        },
    )

    assert blocked.status_code == 429
    assert blocked.json()["detail"]["quota"] == "max_active_monitors"


def test_max_aoi_area_quota_blocks_large_polygon(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
) -> None:
    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    _set_quota(user_id=user_id, max_monitors=10, max_active_monitors=10, max_aoi_area_km2=10.0)

    response = client.post(
        "/monitors",
        json={
            "name": "Large AOI",
            "description": "area should exceed limit",
            "geometry": LARGER_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 50,
        },
    )

    assert response.status_code == 429
    assert response.json()["detail"]["quota"] == "max_aoi_area_km2"


def test_manual_run_quota_denial_does_not_enqueue_task(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.monitors as monitor_routes

    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    monitor_id = _create_monitor(client, name="Run Quota Monitor")
    cleanup_users_and_monitors["monitors"].append(monitor_id)

    _set_quota(user_id=user_id, max_manual_runs_per_day=1, max_concurrent_jobs=10)
    _insert_usage(user_id=user_id, usage_type=USAGE_MANUAL_RUN, quantity=1)

    def _must_not_enqueue(*args, **kwargs):
        raise AssertionError("enqueue_monitor_run_job should not run when quota fails")

    monkeypatch.setattr(monitor_routes, "enqueue_monitor_run_job", _must_not_enqueue)

    response = client.post(f"/monitors/{monitor_id}/runs", json={"lookback_days": 30})
    assert response.status_code == 429
    assert response.json()["detail"]["quota"] == "max_manual_runs_per_day"


def test_concurrent_job_quota_denial_does_not_enqueue_task(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.monitors as monitor_routes

    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    monitor_id = _create_monitor(client, name="Concurrent Quota Monitor")
    cleanup_users_and_monitors["monitors"].append(monitor_id)

    _set_quota(user_id=user_id, max_manual_runs_per_day=100, max_concurrent_jobs=1)

    with SessionLocal() as db_session:
        db_session.add(
            AnalysisJob(
                monitor_id=monitor_id,
                job_type="monitor_run",
                status="queued",
                progress_stage="queued",
                progress_percent=0,
                requested_parameters={},
                result=None,
                error=None,
            )
        )
        db_session.commit()

    def _must_not_enqueue(*args, **kwargs):
        raise AssertionError("enqueue_monitor_run_job should not run when concurrent-job quota fails")

    monkeypatch.setattr(monitor_routes, "enqueue_monitor_run_job", _must_not_enqueue)

    response = client.post(f"/monitors/{monitor_id}/runs", json={"lookback_days": 30})
    assert response.status_code == 429
    assert response.json()["detail"]["quota"] == "max_concurrent_jobs"


def test_observation_search_quota_denial_skips_provider_call(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.monitors as monitor_routes

    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    monitor_id = _create_monitor(client, name="Obs Quota Monitor")
    cleanup_users_and_monitors["monitors"].append(monitor_id)

    _set_quota(user_id=user_id, max_observation_searches_per_day=1)
    _insert_usage(user_id=user_id, usage_type=USAGE_OBSERVATION_SEARCH, quantity=1)

    def _must_not_search(*args, **kwargs):
        raise AssertionError("search_and_store_observations should not run when quota fails")

    monkeypatch.setattr(monitor_routes, "search_and_store_observations", _must_not_search)

    response = client.post(
        f"/monitors/{monitor_id}/observations/search",
        json={"start_date": "2026-08-01", "end_date": "2026-09-01", "max_cloud_cover": 30, "limit": 10},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["quota"] == "max_observation_searches_per_day"


def test_semantic_quota_denial_skips_processing_call(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.monitors as monitor_routes

    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)
    monitor_id = _create_monitor(client, name="Semantic Quota Monitor")
    cleanup_users_and_monitors["monitors"].append(monitor_id)

    _set_quota(user_id=user_id, max_semantic_runs_per_day=1)
    _insert_usage(user_id=user_id, usage_type=USAGE_SEMANTIC_ANALYSIS, quantity=1)

    def _must_not_compute(*args, **kwargs):
        raise AssertionError("compute_change_event_semantics should not run when semantic quota fails")

    monkeypatch.setattr(monitor_routes, "compute_change_event_semantics", _must_not_compute)

    response = client.post(f"/monitors/{monitor_id}/events/{uuid4()}/semantics")
    assert response.status_code == 429
    assert response.json()["detail"]["quota"] == "max_semantic_runs_per_day"


def test_account_usage_counts_today_and_excludes_previous_days(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
) -> None:
    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)

    now = datetime.now(tz=timezone.utc)
    yesterday = now - timedelta(days=1)

    _insert_usage(user_id=user_id, usage_type=USAGE_MANUAL_RUN, quantity=2, created_at=now)
    _insert_usage(user_id=user_id, usage_type=USAGE_MANUAL_RUN, quantity=3, created_at=yesterday)

    response = client.get("/account/usage")
    assert response.status_code == 200
    usage = response.json()["usage_today"]
    assert usage[USAGE_MANUAL_RUN] == 2


def test_admin_role_has_unlimited_effective_quota(
    client: TestClient,
    cleanup_users_and_monitors: dict[str, list[UUID]],
) -> None:
    user_id = _register(client, email=_new_email())
    cleanup_users_and_monitors["users"].append(user_id)

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == user_id)).scalar_one()
        user.role = "admin"
        db_session.add(user)
        db_session.commit()

    response = client.get("/account/quota")
    assert response.status_code == 200
    limits = response.json()["limits"]
    assert all(value is None for value in limits.values())

    with SessionLocal() as db_session:
        admin_user = db_session.execute(select(User).where(User.id == user_id)).scalar_one()
        effective = get_effective_quota_limits(db_session, user=admin_user)

    assert effective.max_monitors is None
    assert effective.max_active_monitors is None
    assert effective.max_aoi_area_km2 is None
    assert effective.max_manual_runs_per_day is None
    assert effective.max_observation_searches_per_day is None
    assert effective.max_semantic_runs_per_day is None
    assert effective.max_concurrent_jobs is None