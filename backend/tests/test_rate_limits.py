from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy import delete

from app.core.config import get_settings
from app.main import app
from app.models import Monitor, User
from app.schemas.jobs import AnalysisJobRead, AnalysisJobType, AnalysisJobStatus, MonitorRunEnqueueResponse, MonitorRunRead, MonitorRunStatus, MonitorRunType


DEFAULT_PASSWORD = "RateLimitPass!234"
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


def _new_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def _register(client: TestClient, *, email: str) -> UUID:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": DEFAULT_PASSWORD, "display_name": "Rate Limit"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["user"]["id"])


def _create_monitor(client: TestClient, *, name: str = "Rate Monitor") -> UUID:
    response = client.post(
        "/monitors",
        json={
            "name": name,
            "description": "Rate test monitor",
            "geometry": VALID_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 20,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _fake_enqueue_response(monitor_id: UUID) -> MonitorRunEnqueueResponse:
    now = datetime.now(tz=timezone.utc)
    job_id = uuid4()
    run_id = uuid4()

    return MonitorRunEnqueueResponse(
        job=AnalysisJobRead(
            id=job_id,
            monitor_id=monitor_id,
            job_type=AnalysisJobType.MONITOR_RUN,
            status=AnalysisJobStatus.QUEUED,
            celery_task_id=f"fake-task-{job_id}",
            progress_stage="queued",
            progress_percent=0,
            requested_parameters={},
            result=None,
            error=None,
            created_at=now,
            started_at=None,
            completed_at=None,
            updated_at=now,
        ),
        run=MonitorRunRead(
            id=run_id,
            monitor_id=monitor_id,
            analysis_job_id=job_id,
            run_type=MonitorRunType.MANUAL,
            status=MonitorRunStatus.STARTED,
            search_window_start=None,
            search_window_end=None,
            observations_found=0,
            observations_inserted=0,
            before_observation_id=None,
            after_observation_id=None,
            before_prepared_id=None,
            after_prepared_id=None,
            analysis_id=None,
            events_generated=0,
            semantics_computed=False,
            impacts_computed=False,
            exposures_computed=False,
            progress_log=[],
            requested_parameters={},
            result=None,
            error=None,
            started_at=now,
            completed_at=None,
            updated_at=now,
        ),
    )


@pytest.fixture
def settings_guard() -> Generator[dict[str, int], None, None]:
    settings = get_settings()
    original = {
        "login": settings.rate_limit_login_per_minute,
        "register": settings.rate_limit_register_per_hour,
        "manual": settings.rate_limit_manual_run_per_minute,
    }
    yield original

    settings.rate_limit_login_per_minute = original["login"]
    settings.rate_limit_register_per_hour = original["register"]
    settings.rate_limit_manual_run_per_minute = original["manual"]


@pytest.fixture
def cleanup_users_monitors() -> Generator[dict[str, list[UUID]], None, None]:
    tracker = {"users": [], "monitors": []}
    yield tracker

    from app.db.session import SessionLocal

    with SessionLocal() as db_session:
        if tracker["monitors"]:
            db_session.execute(delete(Monitor).where(Monitor.id.in_(tracker["monitors"])))
        if tracker["users"]:
            db_session.execute(delete(User).where(User.id.in_(tracker["users"])))
        db_session.commit()


def test_login_rate_limit_enforced_and_returns_structured_error(
    settings_guard: dict[str, int],
    cleanup_users_monitors: dict[str, list[UUID]],
) -> None:
    settings = get_settings()
    settings.rate_limit_login_per_minute = 2

    with TestClient(app) as client:
        email = _new_email("login")
        user_id = _register(client, email=email)
        cleanup_users_monitors["users"].append(user_id)

        first = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
        second = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
        third = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "rate_limited"
    assert third.json()["detail"]["scope"] == "auth_login"


def test_register_rate_limit_enforced(
    settings_guard: dict[str, int],
    cleanup_users_monitors: dict[str, list[UUID]],
) -> None:
    settings = get_settings()
    settings.rate_limit_register_per_hour = 1

    with TestClient(app) as client:
        first = client.post(
            "/auth/register",
            json={"email": _new_email("reg1"), "password": DEFAULT_PASSWORD, "display_name": "First"},
        )
        if first.status_code == 201:
            cleanup_users_monitors["users"].append(UUID(first.json()["user"]["id"]))

        second = client.post(
            "/auth/register",
            json={"email": _new_email("reg2"), "password": DEFAULT_PASSWORD, "display_name": "Second"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["detail"]["scope"] == "auth_register"


def test_manual_run_rate_limit_scopes_by_client_identity(
    settings_guard: dict[str, int],
    cleanup_users_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes.monitors as monitor_routes

    settings = get_settings()
    settings.rate_limit_manual_run_per_minute = 1

    monkeypatch.setattr(
        monitor_routes,
        "enqueue_monitor_run_job",
        lambda db_session, monitor_id, request, run_type: _fake_enqueue_response(monitor_id),
    )

    with TestClient(app, client=("10.10.10.1", 50000)) as client_one:
        user_one_id = _register(client_one, email=_new_email("manual1"))
        cleanup_users_monitors["users"].append(user_one_id)
        monitor_one_id = _create_monitor(client_one, name="Manual One")
        cleanup_users_monitors["monitors"].append(monitor_one_id)

        first = client_one.post(f"/monitors/{monitor_one_id}/runs", json={"lookback_days": 30})
        second = client_one.post(f"/monitors/{monitor_one_id}/runs", json={"lookback_days": 30})

    with TestClient(app, client=("10.10.10.2", 50001)) as client_two:
        user_two_id = _register(client_two, email=_new_email("manual2"))
        cleanup_users_monitors["users"].append(user_two_id)
        monitor_two_id = _create_monitor(client_two, name="Manual Two")
        cleanup_users_monitors["monitors"].append(monitor_two_id)

        third = client_two.post(f"/monitors/{monitor_two_id}/runs", json={"lookback_days": 30})

    assert first.status_code == 202
    assert second.status_code == 429
    assert third.status_code == 202


def test_rate_limit_redis_failure_fails_open(
    settings_guard: dict[str, int],
    cleanup_users_monitors: dict[str, list[UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rate_limit_service as rate_limit_service

    settings = get_settings()
    settings.rate_limit_login_per_minute = 1

    def _broken_client():
        raise RedisError("unavailable")

    monkeypatch.setattr(rate_limit_service, "_redis_client", _broken_client)

    with TestClient(app) as client:
        email = _new_email("redis-open")
        user_id = _register(client, email=email)
        cleanup_users_monitors["users"].append(user_id)

        first = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
        second = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})

    assert first.status_code == 200
    assert second.status_code == 200
