from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models import Alert
from app.services.alert_service import AlertDeliveryError, AlertPersistenceError, deliver_alert_email
from app.tasks.celery_app import celery_app


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _mark_failed(alert_id: UUID, message: str) -> None:
    with SessionLocal() as db_session:
        try:
            alert = db_session.execute(select(Alert).where(Alert.id == alert_id)).scalar_one_or_none()
            if alert is None:
                return
            alert.delivery_status = "failed"
            alert.delivery_error = message
            db_session.add(alert)
            db_session.commit()
        except SQLAlchemyError:
            db_session.rollback()


@celery_app.task(
    name="app.tasks.alerts.deliver_alert_email_task",
    bind=True,
    max_retries=3,
)
def deliver_alert_email_task(self: Task, alert_id: str) -> dict[str, object]:
    try:
        parsed_alert_id = UUID(alert_id)
    except ValueError:
        return {"status": "invalid_alert_id"}

    with SessionLocal() as db_session:
        try:
            result = deliver_alert_email(db_session, alert_id=parsed_alert_id)
        except AlertDeliveryError as exc:
            if exc.retryable and self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=60 * (2 ** int(self.request.retries)))
            _mark_failed(parsed_alert_id, str(exc))
            return {"status": "failed", "alert_id": alert_id}
        except AlertPersistenceError:
            if self.request.retries < self.max_retries:
                raise self.retry(countdown=30 * (2 ** int(self.request.retries)))
            _mark_failed(parsed_alert_id, "Unable to persist email delivery state")
            return {"status": "failed", "alert_id": alert_id}

    if result is None:
        return {"status": "missing", "alert_id": alert_id}
    return {
        "status": result.delivery_status,
        "alert_id": alert_id,
        "delivered_at": _utc_now().isoformat(),
    }
