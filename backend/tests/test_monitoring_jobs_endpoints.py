from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

import app.api.routes.jobs as jobs_routes
import app.services.monitoring_service as monitoring_service
from app.db.session import SessionLocal
from app.main import app
from app.models import AnalysisJob, Monitor, MonitorRun, MonitorSchedule

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


class _FakeAsyncResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_monitor_ids() -> Generator[list[UUID], None, None]:
    monitor_ids: list[UUID] = []
    yield monitor_ids

    if not monitor_ids:
        return

    with SessionLocal() as db_session:
        db_session.execute(delete(Monitor).where(Monitor.id.in_(monitor_ids)))
        db_session.commit()


@pytest.fixture
def fake_send_task(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from app.tasks.celery_app import celery_app

    calls: list[dict[str, object]] = []
    seq = count(1)

    def _send_task(name: str, args: list[object] | None = None, queue: str | None = None, **_: object) -> _FakeAsyncResult:
        task_id = f"task-{next(seq)}"
        calls.append({"name": name, "args": args or [], "queue": queue, "task_id": task_id})
        return _FakeAsyncResult(task_id)

    monkeypatch.setattr(celery_app, "send_task", _send_task)
    return calls


def build_monitor_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Monitoring Test Monitor",
        "description": "Monitor for monitoring job tests",
        "geometry": deepcopy(MONITOR_POLYGON),
        "monitor_type": "general",
        "sensitivity": 0.5,
        "minimum_change_area_m2": 10.0,
    }
    payload.update(overrides)
    return payload


def create_monitor_and_track(client: TestClient, created_monitor_ids: list[UUID], **overrides: object) -> dict[str, object]:
    response = client.post("/monitors", json=build_monitor_payload(**overrides))
    assert response.status_code == 201
    body = response.json()
    created_monitor_ids.append(UUID(body["id"]))
    return body


def test_post_run_returns_202_and_creates_job_and_run(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    response = client.post(f"/monitors/{monitor['id']}/runs", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["job"]["status"] == "queued"
    assert body["run"]["status"] == "started"
    assert body["run"]["monitor_id"] == monitor["id"]
    assert fake_send_task[0]["name"] == "app.tasks.monitoring.run_monitor_workflow_task"


def test_post_run_missing_monitor_returns_404(
    client: TestClient,
    fake_send_task: list[dict[str, object]],
) -> None:
    response = client.post(f"/monitors/{uuid4()}/runs", json={})
    assert response.status_code == 404


def test_post_run_active_run_returns_409(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    first = client.post(f"/monitors/{monitor['id']}/runs", json={})
    second = client.post(f"/monitors/{monitor['id']}/runs", json={})

    assert first.status_code == 202
    assert second.status_code == 409


def test_post_run_redis_queue_failure_returns_503_and_marks_failed(
    client: TestClient,
    created_monitor_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.celery_app import celery_app

    monitor = create_monitor_and_track(client, created_monitor_ids)

    def _raise_send_task(*_: object, **__: object):
        raise OSError("broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", _raise_send_task)

    response = client.post(f"/monitors/{monitor['id']}/runs", json={})
    assert response.status_code == 503

    monitor_id = UUID(monitor["id"])
    with SessionLocal() as db_session:
        row = db_session.execute(
            select(AnalysisJob, MonitorRun)
            .join(MonitorRun, MonitorRun.analysis_job_id == AnalysisJob.id)
            .where(AnalysisJob.monitor_id == monitor_id)
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        ).one()

    job, run = row
    assert job.status == "failed"
    assert run.status == "failed"
    assert isinstance(job.error, dict)
    assert job.error.get("type") == "queue_unavailable"


def test_get_job_and_cancel_job(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    enqueue_response = client.post(f"/monitors/{monitor['id']}/runs", json={})
    assert enqueue_response.status_code == 202
    job_id = enqueue_response.json()["job"]["id"]

    get_response = client.get(f"/jobs/{job_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == job_id

    cancel_response = client.post(f"/jobs/{job_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["cancelled"] is True
    assert cancel_response.json()["job"]["status"] == "cancelled"

    second_cancel = client.post(f"/jobs/{job_id}/cancel")
    assert second_cancel.status_code == 200
    assert second_cancel.json()["job"]["status"] == "cancelled"


def test_get_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get(f"/jobs/{uuid4()}")
    assert response.status_code == 404


def test_monitor_runs_list_and_detail(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    enqueue_response = client.post(f"/monitors/{monitor['id']}/runs", json={})
    assert enqueue_response.status_code == 202
    run_id = enqueue_response.json()["run"]["id"]

    list_response = client.get(f"/monitors/{monitor['id']}/runs?limit=50&offset=0")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get(f"/monitors/{monitor['id']}/runs/{run_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == run_id


def test_monitor_runs_status_filter_and_validation(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])
    enqueue_response = client.post(f"/monitors/{monitor['id']}/runs", json={})
    assert enqueue_response.status_code == 202
    run_id = UUID(enqueue_response.json()["run"]["id"])

    with SessionLocal() as db_session:
        run = db_session.execute(select(MonitorRun).where(MonitorRun.id == run_id)).scalar_one()
        run.status = "succeeded"
        db_session.add(run)

        job = db_session.execute(select(AnalysisJob).where(AnalysisJob.id == run.analysis_job_id)).scalar_one()
        job.status = "succeeded"
        db_session.add(job)
        db_session.commit()

    filtered = client.get(f"/monitors/{monitor_id}/runs?status=succeeded")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    invalid = client.get(f"/monitors/{monitor_id}/runs?status=not-a-status")
    assert invalid.status_code == 422


def test_monitor_schedule_patch_get_enable_disable(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    enabled_response = client.patch(
        f"/monitors/{monitor['id']}/schedule",
        json={"enabled": True, "interval_hours": 1},
    )
    assert enabled_response.status_code == 200
    enabled_body = enabled_response.json()
    assert enabled_body["enabled"] is True
    assert enabled_body["interval_hours"] == 1
    assert enabled_body["cadence_minutes"] == 60
    assert enabled_body["next_run_at"] is not None

    get_response = client.get(f"/monitors/{monitor['id']}/schedule")
    assert get_response.status_code == 200
    assert get_response.json()["enabled"] is True

    disabled_response = client.patch(
        f"/monitors/{monitor['id']}/schedule",
        json={"enabled": False, "interval_hours": 1},
    )
    assert disabled_response.status_code == 200
    assert disabled_response.json()["next_run_at"] is None


def test_monitor_schedule_validation_and_not_found(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)

    invalid = client.patch(
        f"/monitors/{monitor['id']}/schedule",
        json={"enabled": True, "interval_hours": 0},
    )
    assert invalid.status_code == 422

    missing = client.patch(
        f"/monitors/{uuid4()}/schedule",
        json={"enabled": True, "interval_hours": 1},
    )
    assert missing.status_code == 404

    get_missing = client.get(f"/monitors/{monitor['id']}/schedule")
    assert get_missing.status_code == 404


def test_worker_health_endpoint_states(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_routes, "redis_ping_status", lambda: (True, None))
    monkeypatch.setattr(jobs_routes, "celery_worker_ping", lambda: (True, 1))

    healthy = client.get("/worker/health")
    assert healthy.status_code == 200
    assert healthy.json()["status"] == "healthy"

    monkeypatch.setattr(jobs_routes, "redis_ping_status", lambda: (False, "ConnectionError"))
    monkeypatch.setattr(jobs_routes, "celery_worker_ping", lambda: (False, 0))

    degraded = client.get("/worker/health")
    assert degraded.status_code == 503
    assert degraded.json()["status"] == "degraded"
    assert degraded.json()["redis"] == "down"


def test_analysis_job_active_partial_unique_constraint(
    client: TestClient,
    created_monitor_ids: list[UUID],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    with SessionLocal() as db_session:
        first = AnalysisJob(
            monitor_id=monitor_id,
            job_type="monitor_run",
            status="queued",
            progress_stage="queued",
            progress_percent=0.0,
            requested_parameters={},
        )
        db_session.add(first)
        db_session.commit()

        second = AnalysisJob(
            monitor_id=monitor_id,
            job_type="monitor_run",
            status="running",
            progress_stage="running",
            progress_percent=10.0,
            requested_parameters={},
        )
        db_session.add(second)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_scheduler_scan_only_active_due_and_no_duplicate(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    active_monitor = create_monitor_and_track(client, created_monitor_ids, name="Active Monitor")
    paused_monitor = create_monitor_and_track(client, created_monitor_ids, name="Paused Monitor")

    paused_update = client.patch(f"/monitors/{paused_monitor['id']}", json={"status": "paused"})
    assert paused_update.status_code == 200

    schedule_active = client.patch(
        f"/monitors/{active_monitor['id']}/schedule",
        json={"enabled": True, "interval_hours": 1},
    )
    assert schedule_active.status_code == 200

    schedule_paused = client.patch(
        f"/monitors/{paused_monitor['id']}/schedule",
        json={"enabled": True, "interval_hours": 1},
    )
    assert schedule_paused.status_code == 200

    first_scan = monitoring_service.scan_monitor_schedules(max_due=10)
    assert first_scan["lock_acquired"] is True
    assert first_scan["enqueued"] == 1

    active_id = UUID(active_monitor["id"])
    paused_id = UUID(paused_monitor["id"])

    with SessionLocal() as db_session:
        active_jobs = int(
            db_session.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.monitor_id == active_id)
            ).scalar_one()
        )
        paused_jobs = int(
            db_session.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.monitor_id == paused_id)
            ).scalar_one()
        )

        assert active_jobs == 1
        assert paused_jobs == 0

        schedule_row = db_session.execute(
            select(MonitorSchedule).where(MonitorSchedule.monitor_id == active_id)
        ).scalar_one()
        schedule_row.next_run_after = datetime.now(timezone.utc) - timedelta(minutes=1)
        db_session.add(schedule_row)
        db_session.commit()

    second_scan = monitoring_service.scan_monitor_schedules(max_due=10)
    assert second_scan["lock_acquired"] is True
    assert second_scan["enqueued"] == 0
    assert second_scan["skipped_overlap"] >= 1

    with SessionLocal() as db_session:
        active_jobs_after = int(
            db_session.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.monitor_id == active_id)
            ).scalar_one()
        )
        assert active_jobs_after == 1


def test_delete_monitor_cascades_jobs_runs_and_schedule(
    client: TestClient,
    created_monitor_ids: list[UUID],
    fake_send_task: list[dict[str, object]],
) -> None:
    monitor = create_monitor_and_track(client, created_monitor_ids)
    monitor_id = UUID(monitor["id"])

    enqueue_response = client.post(f"/monitors/{monitor['id']}/runs", json={})
    assert enqueue_response.status_code == 202

    schedule_response = client.patch(
        f"/monitors/{monitor['id']}/schedule",
        json={"enabled": True, "interval_hours": 1},
    )
    assert schedule_response.status_code == 200

    delete_response = client.delete(f"/monitors/{monitor['id']}")
    assert delete_response.status_code == 204

    created_monitor_ids.remove(monitor_id)

    with SessionLocal() as db_session:
        jobs_count = int(
            db_session.execute(
                select(func.count(AnalysisJob.id)).where(AnalysisJob.monitor_id == monitor_id)
            ).scalar_one()
        )
        runs_count = int(
            db_session.execute(
                select(func.count(MonitorRun.id)).where(MonitorRun.monitor_id == monitor_id)
            ).scalar_one()
        )
        schedule_count = int(
            db_session.execute(
                select(func.count(MonitorSchedule.id)).where(MonitorSchedule.monitor_id == monitor_id)
            ).scalar_one()
        )

    assert jobs_count == 0
    assert runs_count == 0
    assert schedule_count == 0


def test_root_health_ready_regression(client: TestClient) -> None:
    root_response = client.get("/")
    health_response = client.get("/health")
    ready_response = client.get("/ready")

    assert root_response.status_code == 200
    assert health_response.status_code == 200
    assert ready_response.status_code == 200
