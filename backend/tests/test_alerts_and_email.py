from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.main import app
from app.models import Alert, AnalysisJob, Monitor, MonitorRun, NotificationPreference, User
from app.services.alert_service import (
    AlertDeliveryError,
    create_alert,
    create_run_status_alert,
    deliver_alert_email,
)
from app.services.email_service import EmailDeliveryResult, EmailMessage, EmailProvider, EmailProviderError
from app.tasks.alerts import deliver_alert_email_task


DEFAULT_PASSWORD = "AlertsPass!234"
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
        json={"email": email, "password": DEFAULT_PASSWORD, "display_name": "Alerts User"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["user"]["id"])


def _create_monitor(client: TestClient) -> UUID:
    response = client.post(
        "/monitors",
        json={
            "name": "Alerts Monitor",
            "description": "Alert test monitor",
            "geometry": VALID_POLYGON,
            "monitor_type": "general",
            "sensitivity": 0.5,
            "minimum_change_area_m2": 20,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


@pytest.fixture
def alert_fixture() -> Generator[dict[str, object], None, None]:
    user_id: UUID | None = None
    monitor_id: UUID | None = None

    with TestClient(app) as client:
        user_id = _register(client, email=f"alerts-{uuid4().hex}@example.com")
        monitor_id = _create_monitor(client)

        with SessionLocal() as db_session:
            job = AnalysisJob(
                monitor_id=monitor_id,
                job_type="monitor_run",
                status="succeeded",
                progress_stage="completed",
                progress_percent=100,
                requested_parameters={},
                result={},
                error=None,
            )
            db_session.add(job)
            db_session.flush()

            run = MonitorRun(
                monitor_id=monitor_id,
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
            db_session.commit()
            run_id = run.id

        yield {
            "client": client,
            "user_id": user_id,
            "monitor_id": monitor_id,
            "run_id": run_id,
        }

    with SessionLocal() as db_session:
        if monitor_id is not None:
            db_session.execute(delete(Monitor).where(Monitor.id == monitor_id))
        if user_id is not None:
            db_session.execute(delete(User).where(User.id == user_id))
        db_session.commit()


def test_new_event_alert_persists_and_deduplicates(alert_fixture: dict[str, object]) -> None:
    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()

        first = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="new_change_event",
            severity="medium",
            title="New change event detected",
            message="ARGUS detected a new observable land-surface change.",
            monitor_run_id=alert_fixture["run_id"],
            change_event_id=None,
            metadata={"confidence": 0.74},
        )
        assert first is not None

        second = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="new_change_event",
            severity="medium",
            title="New change event detected",
            message="ARGUS detected a new observable land-surface change.",
            monitor_run_id=alert_fixture["run_id"],
            change_event_id=None,
            metadata={"confidence": 0.74},
        )

        db_session.commit()
        assert second is not None
        assert second.id == first.id


def test_run_failed_and_partial_alerts_respect_notification_preferences(alert_fixture: dict[str, object]) -> None:
    with SessionLocal() as db_session:
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()
        run = db_session.execute(select(MonitorRun).where(MonitorRun.id == alert_fixture["run_id"])).scalar_one()

        create_run_status_alert(db_session, monitor=monitor, run=run, status="partial", warnings=["w1"])
        create_run_status_alert(db_session, monitor=monitor, run=run, status="failed", warnings=["w2"])
        db_session.commit()

        types = {
            row.alert_type
            for row in db_session.execute(
                select(Alert).where(Alert.user_id == alert_fixture["user_id"])
            ).scalars().all()
        }
        assert "run_partial" in types
        assert "run_failed" in types

        pref = db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == alert_fixture["user_id"],
                NotificationPreference.monitor_id.is_(None),
            )
        ).scalar_one()
        pref.notify_on_partial_run = False
        db_session.add(pref)

        next_job = AnalysisJob(
            monitor_id=monitor.id,
            job_type="monitor_run",
            status="queued",
            progress_stage="queued",
            progress_percent=0,
            requested_parameters={},
            result=None,
            error=None,
        )
        db_session.add(next_job)
        db_session.flush()

        next_run = MonitorRun(
            monitor_id=monitor.id,
            analysis_job_id=next_job.id,
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
        db_session.add(next_run)
        db_session.flush()

        create_run_status_alert(db_session, monitor=monitor, run=next_run, status="partial", warnings=[])
        db_session.commit()

        partial_alerts = db_session.execute(
            select(Alert).where(
                Alert.user_id == alert_fixture["user_id"],
                Alert.alert_type == "run_partial",
            )
        ).scalars().all()

        assert len(partial_alerts) == 1


def test_minimum_severity_filter_blocks_low_alert(alert_fixture: dict[str, object]) -> None:
    with SessionLocal() as db_session:
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()

        pref = db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.monitor_id.is_(None),
            )
        ).scalar_one()
        pref.minimum_event_severity = "high"
        db_session.add(pref)
        db_session.flush()

        blocked = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="semantic_change",
            severity="low",
            title="Low significance semantic label",
            message="Observable pattern remains uncertain.",
            metadata={"semantic_label": "uncertain", "semantic_confidence": 0.32},
        )
        db_session.commit()

        assert blocked is None


def test_alert_message_safety_for_uncertain_semantic_content(alert_fixture: dict[str, object]) -> None:
    with SessionLocal() as db_session:
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()

        alert = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="semantic_change",
            severity="medium",
            title="Semantic interpretation available",
            message="Observable land-surface pattern is uncertain and requires review.",
            metadata={"semantic_label": "uncertain", "semantic_confidence": 0.41},
        )
        db_session.commit()
        assert alert is not None

        assert "damaged" not in alert.message.lower()
        assert "destroyed" not in alert.message.lower()


def test_alert_endpoints_mark_read_unread_unread_filter_and_pagination(alert_fixture: dict[str, object]) -> None:
    client = alert_fixture["client"]
    assert isinstance(client, TestClient)

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()

        alerts: list[Alert] = []
        for index in range(3):
            created = create_alert(
                db_session,
                user=user,
                monitor=monitor,
                alert_type="run_failed" if index == 0 else "run_partial",
                severity="high" if index == 0 else "medium",
                title=f"Alert {index}",
                message=f"Alert message {index}",
                monitor_run_id=alert_fixture["run_id"],
                change_event_id=None,
                metadata={"index": index},
            )
            if created is not None:
                alerts.append(created)
        db_session.commit()

    list_response = client.get("/alerts?limit=2&offset=0")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 2

    unread_before = client.get("/alerts?unread_only=true")
    assert unread_before.status_code == 200
    assert unread_before.json()["count"] >= 1

    target_id = unread_before.json()["alerts"][0]["id"]

    mark_read = client.patch(f"/alerts/{target_id}", json={"status": "read"})
    assert mark_read.status_code == 200
    assert mark_read.json()["status"] == "read"
    assert mark_read.json()["read_at"] is not None

    unread_after_read = client.get("/alerts?unread_only=true")
    assert unread_after_read.status_code == 200
    assert all(row["id"] != target_id for row in unread_after_read.json()["alerts"])

    mark_unread = client.patch(f"/alerts/{target_id}", json={"status": "unread"})
    assert mark_unread.status_code == 200
    assert mark_unread.json()["status"] == "unread"
    assert mark_unread.json()["read_at"] is None


def test_disabled_notification_type_prevents_alert_creation(alert_fixture: dict[str, object]) -> None:
    with SessionLocal() as db_session:
        pref = db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == alert_fixture["user_id"],
                NotificationPreference.monitor_id.is_(None),
            )
        ).scalar_one()
        pref.notify_on_failed_run = False
        db_session.add(pref)

        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()
        run = db_session.execute(select(MonitorRun).where(MonitorRun.id == alert_fixture["run_id"])).scalar_one()

        create_run_status_alert(db_session, monitor=monitor, run=run, status="failed", warnings=["error"])
        db_session.commit()

        failed_alerts = db_session.execute(
            select(Alert).where(
                Alert.user_id == alert_fixture["user_id"],
                Alert.alert_type == "run_failed",
            )
        ).scalars().all()

    assert failed_alerts == []


def test_email_delivery_success_and_no_duplicate_send(alert_fixture: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    class FakeProvider(EmailProvider):
        name = "fake"

        def send(self, message: EmailMessage) -> EmailDeliveryResult:
            calls["count"] += 1
            return EmailDeliveryResult(status="delivered", provider_message_id="provider-1")

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()

        pref = db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.monitor_id.is_(None),
            )
        ).scalar_one()
        pref.email_enabled = True
        db_session.add(pref)

        alert = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="run_partial",
            severity="medium",
            title="Email success",
            message="Email test",
            monitor_run_id=alert_fixture["run_id"],
            metadata={},
        )
        db_session.commit()
        assert alert is not None
        alert_id = alert.id

    import app.services.alert_service as alert_service

    monkeypatch.setattr(alert_service, "get_email_provider", lambda: FakeProvider())

    with SessionLocal() as db_session:
        first = deliver_alert_email(db_session, alert_id=alert_id)
        assert first is not None
        assert first.delivery_status == "delivered"

    with SessionLocal() as db_session:
        second = deliver_alert_email(db_session, alert_id=alert_id)
        assert second is not None
        assert second.delivery_status == "delivered"

    assert calls["count"] == 1


def test_email_delivery_provider_not_configured_sets_disabled_state(alert_fixture: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    class DisabledProvider(EmailProvider):
        name = "none"

        def send(self, message: EmailMessage) -> EmailDeliveryResult:
            return EmailDeliveryResult(status="disabled", error="not configured")

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()
        alert = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="run_partial",
            severity="medium",
            title="Email disabled",
            message="No provider",
            monitor_run_id=alert_fixture["run_id"],
            metadata={},
        )
        assert alert is not None
        db_session.commit()
        alert_id = alert.id

    import app.services.alert_service as alert_service

    monkeypatch.setattr(alert_service, "get_email_provider", lambda: DisabledProvider())

    with SessionLocal() as db_session:
        delivered = deliver_alert_email(db_session, alert_id=alert_id)
        assert delivered is not None
        assert delivered.delivery_status == "disabled"


def test_email_delivery_transient_failure_and_terminal_failure(alert_fixture: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    class TransientProvider(EmailProvider):
        name = "transient"

        def send(self, message: EmailMessage) -> EmailDeliveryResult:
            raise EmailProviderError("transient", retryable=True)

    class TerminalProvider(EmailProvider):
        name = "terminal"

        def send(self, message: EmailMessage) -> EmailDeliveryResult:
            return EmailDeliveryResult(status="failed", error="terminal")

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == alert_fixture["user_id"])).scalar_one()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert_fixture["monitor_id"])).scalar_one()

        transient_alert = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="run_partial",
            severity="medium",
            title="Transient",
            message="Transient provider",
            monitor_run_id=alert_fixture["run_id"],
            metadata={},
        )
        terminal_alert = create_alert(
            db_session,
            user=user,
            monitor=monitor,
            alert_type="run_failed",
            severity="high",
            title="Terminal",
            message="Terminal provider",
            monitor_run_id=alert_fixture["run_id"],
            metadata={},
        )
        assert transient_alert is not None
        assert terminal_alert is not None
        db_session.commit()
        transient_id = transient_alert.id
        terminal_id = terminal_alert.id

    import app.services.alert_service as alert_service

    monkeypatch.setattr(alert_service, "get_email_provider", lambda: TransientProvider())
    with SessionLocal() as db_session:
        with pytest.raises(AlertDeliveryError):
            deliver_alert_email(db_session, alert_id=transient_id)

    with SessionLocal() as db_session:
        queued = db_session.execute(select(Alert).where(Alert.id == transient_id)).scalar_one()
        assert queued.delivery_status == "queued"

    monkeypatch.setattr(alert_service, "get_email_provider", lambda: TerminalProvider())
    with SessionLocal() as db_session:
        delivered = deliver_alert_email(db_session, alert_id=terminal_id)
        assert delivered is not None
        assert delivered.delivery_status == "failed"


def test_email_task_retry_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.alerts as alerts_tasks

    monkeypatch.setattr(
        alerts_tasks,
        "deliver_alert_email",
        lambda db_session, alert_id: (_ for _ in ()).throw(AlertDeliveryError("transient", retryable=True)),
    )

    def _retry(*args, **kwargs):
        raise RuntimeError("retry-called")

    monkeypatch.setattr(alerts_tasks.deliver_alert_email_task, "retry", _retry)

    task = alerts_tasks.deliver_alert_email_task
    task.push_request(retries=0)
    try:
        with pytest.raises(RuntimeError, match="retry-called"):
            task.run(str(uuid4()))
    finally:
        task.pop_request()
