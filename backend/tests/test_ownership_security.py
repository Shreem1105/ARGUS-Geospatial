from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models import Alert, AnalysisJob, Monitor, MonitorRun, User


DEFAULT_PASSWORD = "OwnershipPass!234"
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


def _register(client: TestClient, *, email: str) -> UUID:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": DEFAULT_PASSWORD,
            "display_name": "Ownership Test",
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["user"]["id"])


@pytest.fixture
def ownership_fixture() -> Generator[dict[str, object], None, None]:
    created_monitor_id: UUID | None = None
    user_a_id: UUID | None = None
    user_b_id: UUID | None = None

    with TestClient(app) as client_a, TestClient(app) as client_b:
        user_a_id = _register(client_a, email=f"owner-a-{uuid4().hex}@example.com")
        user_b_id = _register(client_b, email=f"owner-b-{uuid4().hex}@example.com")

        monitor_response = client_a.post(
            "/monitors",
            json={
                "name": "Owner A Monitor",
                "description": "Ownership test monitor",
                "geometry": VALID_POLYGON,
                "monitor_type": "general",
                "sensitivity": 0.5,
                "minimum_change_area_m2": 20,
            },
        )
        assert monitor_response.status_code == 201, monitor_response.text
        created_monitor_id = UUID(monitor_response.json()["id"])

        with SessionLocal() as db_session:
            job = AnalysisJob(
                monitor_id=created_monitor_id,
                job_type="monitor_run",
                status="queued",
                progress_stage="queued",
                progress_percent=0,
                requested_parameters={"reason": "ownership-test"},
                result=None,
                error=None,
            )
            db_session.add(job)
            db_session.flush()

            run = MonitorRun(
                monitor_id=created_monitor_id,
                analysis_job_id=job.id,
                run_type="manual",
                status="started",
                observations_found=0,
                observations_inserted=0,
                events_generated=0,
                progress_log=[],
                requested_parameters={},
                result=None,
                error=None,
                started_at=datetime.now(tz=timezone.utc),
            )
            db_session.add(run)
            db_session.flush()

            alert = Alert(
                user_id=user_a_id,
                monitor_id=created_monitor_id,
                monitor_run_id=run.id,
                change_event_id=None,
                alert_type="run_partial",
                severity="medium",
                title="Run partial",
                message="Ownership validation alert",
                status="unread",
                delivery_status="disabled",
                delivery_error=None,
                metadata_={},
            )
            db_session.add(alert)
            db_session.commit()

            job_id = job.id
            run_id = run.id
            alert_id = alert.id

        yield {
            "client_a": client_a,
            "client_b": client_b,
            "user_a_id": user_a_id,
            "user_b_id": user_b_id,
            "monitor_id": created_monitor_id,
            "job_id": job_id,
            "run_id": run_id,
            "alert_id": alert_id,
            "observation_id": uuid4(),
            "analysis_id": uuid4(),
            "event_id": uuid4(),
        }

    with SessionLocal() as db_session:
        if created_monitor_id is not None:
            db_session.execute(delete(Monitor).where(Monitor.id == created_monitor_id))
        if user_a_id is not None:
            db_session.execute(delete(User).where(User.id == user_a_id))
        if user_b_id is not None:
            db_session.execute(delete(User).where(User.id == user_b_id))
        db_session.commit()


@pytest.mark.parametrize(
    ("method", "path_template", "json_body"),
    [
        ("GET", "/monitors/{monitor_id}", None),
        ("PATCH", "/monitors/{monitor_id}", {"name": "attempted"}),
        ("DELETE", "/monitors/{monitor_id}", None),
        ("GET", "/monitors/{monitor_id}/summary", None),
        ("POST", "/monitors/{monitor_id}/intersects", {"geometry": VALID_POLYGON}),
        ("POST", "/monitors/{monitor_id}/observations/search", {"start_date": "2026-08-01", "end_date": "2026-08-15", "max_cloud_cover": 30, "limit": 5}),
        ("GET", "/monitors/{monitor_id}/observations", None),
        ("GET", "/monitors/{monitor_id}/observations/{observation_id}", None),
        ("POST", "/monitors/{monitor_id}/observations/{observation_id}/prepare", {"force_reprocess": False}),
        ("GET", "/monitors/{monitor_id}/observations/{observation_id}/prepared", None),
        ("GET", "/monitors/{monitor_id}/analyses", None),
        ("GET", "/monitors/{monitor_id}/events", None),
        ("GET", "/monitors/{monitor_id}/events/{event_id}", None),
        ("POST", "/monitors/{monitor_id}/events/{event_id}/semantics", {"force_recompute": False}),
        ("GET", "/monitors/{monitor_id}/events/{event_id}/impact", None),
        ("POST", "/monitors/{monitor_id}/events/{event_id}/impact", None),
        ("GET", "/monitors/{monitor_id}/events/{event_id}/exposure", None),
        ("POST", "/monitors/{monitor_id}/events/{event_id}/exposure", None),
        ("GET", "/monitors/{monitor_id}/events/{event_id}/intelligence", None),
        ("POST", "/monitors/{monitor_id}/context/refresh", None),
        ("GET", "/monitors/{monitor_id}/context", None),
        ("GET", "/monitors/{monitor_id}/impact/summary", None),
        ("GET", "/monitors/{monitor_id}/exposure/summary", None),
        ("GET", "/monitors/{monitor_id}/runs", None),
        ("POST", "/monitors/{monitor_id}/runs", {"lookback_days": 30}),
        ("GET", "/monitors/{monitor_id}/runs/{run_id}", None),
        ("PATCH", "/monitors/{monitor_id}/schedule", {"enabled": True, "interval_hours": 24}),
        ("GET", "/monitors/{monitor_id}/schedule", None),
        ("GET", "/monitors/{monitor_id}/observations/{observation_id}/prepared/artifacts/preview", None),
        ("GET", "/monitors/{monitor_id}/analyses/{analysis_id}/artifacts/preview", None),
    ],
)
def test_user_b_cannot_access_user_a_monitor_resources(
    ownership_fixture: dict[str, object],
    method: str,
    path_template: str,
    json_body: dict[str, object] | None,
) -> None:
    client_b = ownership_fixture["client_b"]
    assert isinstance(client_b, TestClient)

    path = path_template.format(
        monitor_id=ownership_fixture["monitor_id"],
        run_id=ownership_fixture["run_id"],
        observation_id=ownership_fixture["observation_id"],
        analysis_id=ownership_fixture["analysis_id"],
        event_id=ownership_fixture["event_id"],
    )

    if method == "GET":
        response = client_b.get(path)
    elif method == "POST":
        response = client_b.post(path, json=json_body)
    elif method == "PATCH":
        response = client_b.patch(path, json=json_body)
    elif method == "DELETE":
        response = client_b.delete(path)
    else:
        raise AssertionError(f"Unsupported method {method}")

    assert response.status_code == 404


def test_user_b_cannot_access_user_a_job_by_uuid(ownership_fixture: dict[str, object]) -> None:
    client_b = ownership_fixture["client_b"]
    assert isinstance(client_b, TestClient)
    job_id = ownership_fixture["job_id"]

    get_response = client_b.get(f"/jobs/{job_id}")
    cancel_response = client_b.post(f"/jobs/{job_id}/cancel")

    assert get_response.status_code == 404
    assert cancel_response.status_code == 404


def test_user_b_cannot_read_or_patch_user_a_alert(ownership_fixture: dict[str, object]) -> None:
    client_a = ownership_fixture["client_a"]
    client_b = ownership_fixture["client_b"]
    assert isinstance(client_a, TestClient)
    assert isinstance(client_b, TestClient)

    alert_id = ownership_fixture["alert_id"]

    list_response = client_b.get("/alerts")
    assert list_response.status_code == 200
    assert all(row["id"] != str(alert_id) for row in list_response.json()["alerts"])

    get_response = client_b.get(f"/alerts/{alert_id}")
    patch_response = client_b.patch(f"/alerts/{alert_id}", json={"status": "read"})
    owner_response = client_a.get(f"/alerts/{alert_id}")

    assert get_response.status_code == 404
    assert patch_response.status_code == 404
    assert owner_response.status_code == 200


def test_monitor_scoped_notification_preferences_respect_ownership(ownership_fixture: dict[str, object]) -> None:
    client_a = ownership_fixture["client_a"]
    client_b = ownership_fixture["client_b"]
    assert isinstance(client_a, TestClient)
    assert isinstance(client_b, TestClient)

    monitor_id = ownership_fixture["monitor_id"]

    owner_pref = client_a.get(f"/account/notifications/preferences?monitor_id={monitor_id}")
    blocked_get = client_b.get(f"/account/notifications/preferences?monitor_id={monitor_id}")
    blocked_patch = client_b.patch(
        f"/account/notifications/preferences?monitor_id={monitor_id}",
        json={"notify_on_new_event": False},
    )

    assert owner_pref.status_code == 200
    assert blocked_get.status_code == 404
    assert blocked_patch.status_code == 404


def test_monitor_list_is_user_scoped(ownership_fixture: dict[str, object]) -> None:
    client_a = ownership_fixture["client_a"]
    client_b = ownership_fixture["client_b"]
    assert isinstance(client_a, TestClient)
    assert isinstance(client_b, TestClient)

    monitor_id = str(ownership_fixture["monitor_id"])

    owner_list = client_a.get("/monitors")
    other_list = client_b.get("/monitors")

    assert owner_list.status_code == 200
    assert other_list.status_code == 200
    assert any(row["id"] == monitor_id for row in owner_list.json())
    assert all(row["id"] != monitor_id for row in other_list.json())


def test_public_explore_is_anonymous_but_private_resources_are_not(ownership_fixture: dict[str, object]) -> None:
    monitor_id = ownership_fixture["monitor_id"]

    with TestClient(app) as anonymous_client:
        explore_response = anonymous_client.get("/explore/monitors", headers={"x-argus-test-no-auto-auth": "1"})
        private_response = anonymous_client.get(f"/monitors/{monitor_id}", headers={"x-argus-test-no-auto-auth": "1"})
        alerts_response = anonymous_client.get("/alerts", headers={"x-argus-test-no-auto-auth": "1"})
        jobs_response = anonymous_client.get(f"/jobs/{ownership_fixture['job_id']}", headers={"x-argus-test-no-auto-auth": "1"})

    assert explore_response.status_code == 200
    assert private_response.status_code == 401
    assert alerts_response.status_code == 401
    assert jobs_response.status_code == 401