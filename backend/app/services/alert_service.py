from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Alert, Monitor, MonitorRun, NotificationPreference, User
from app.schemas.account import NotificationPreferenceRead, NotificationPreferenceUpdateRequest
from app.schemas.alert import AlertRead
from app.services.email_service import EmailMessage, EmailProviderError, get_email_provider

logger = logging.getLogger(__name__)


class AlertQueryError(Exception):
    pass


class AlertPersistenceError(Exception):
    pass


class AlertDeliveryError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


SEVERITY_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _to_alert_read(alert: Alert) -> AlertRead:
    return AlertRead(
        id=alert.id,
        user_id=alert.user_id,
        monitor_id=alert.monitor_id,
        monitor_run_id=alert.monitor_run_id,
        change_event_id=alert.change_event_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        title=alert.title,
        message=alert.message,
        status=alert.status,
        created_at=alert.created_at,
        read_at=alert.read_at,
        delivery_status=alert.delivery_status,
        delivery_error=alert.delivery_error,
        metadata=alert.metadata_,
    )


def _to_pref_read(pref: NotificationPreference) -> NotificationPreferenceRead:
    return NotificationPreferenceRead(
        id=pref.id,
        user_id=pref.user_id,
        monitor_id=pref.monitor_id,
        in_app_enabled=pref.in_app_enabled,
        email_enabled=pref.email_enabled,
        minimum_event_severity=pref.minimum_event_severity,
        minimum_semantic_confidence=pref.minimum_semantic_confidence,
        notify_on_new_event=pref.notify_on_new_event,
        notify_on_failed_run=pref.notify_on_failed_run,
        notify_on_partial_run=pref.notify_on_partial_run,
        created_at=pref.created_at,
        updated_at=pref.updated_at,
    )


def _load_existing_alert(
    db_session: Session,
    *,
    user_id: UUID,
    alert_type: str,
    monitor_run_id: UUID | None,
    change_event_id: UUID | None,
) -> Alert | None:
    try:
        return db_session.execute(
            select(Alert).where(
                Alert.user_id == user_id,
                Alert.alert_type == alert_type,
                Alert.monitor_run_id == monitor_run_id,
                Alert.change_event_id == change_event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to query alert") from exc


def _get_preference(
    db_session: Session,
    *,
    user_id: UUID,
    monitor_id: UUID | None,
) -> NotificationPreference | None:
    try:
        if monitor_id is not None:
            monitor_pref = db_session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.monitor_id == monitor_id,
                )
            ).scalar_one_or_none()
            if monitor_pref is not None:
                return monitor_pref

        return db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.monitor_id.is_(None),
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to load notification preference") from exc


def _ensure_global_preference(db_session: Session, *, user_id: UUID) -> NotificationPreference:
    existing = _get_preference(db_session, user_id=user_id, monitor_id=None)
    if existing is not None:
        return existing

    pref = NotificationPreference(
        user_id=user_id,
        monitor_id=None,
        in_app_enabled=True,
        email_enabled=False,
        minimum_event_severity="low",
        minimum_semantic_confidence=None,
        notify_on_new_event=True,
        notify_on_failed_run=True,
        notify_on_partial_run=True,
    )
    db_session.add(pref)
    db_session.flush()
    return pref


def _passes_minimum_severity(*, minimum_event_severity: str, severity: str) -> bool:
    threshold = SEVERITY_ORDER.get(minimum_event_severity, 1)
    value = SEVERITY_ORDER.get(severity, 1)
    return value >= threshold


def _queue_alert_email(alert_id: UUID) -> None:
    provider = get_email_provider()
    if provider.name == "none":
        return

    try:
        from app.tasks.celery_app import celery_app

        celery_app.send_task(
            "app.tasks.alerts.deliver_alert_email_task",
            args=[str(alert_id)],
            queue="monitoring",
            ignore_result=True,
            retry=False,
        )
    except Exception:
        logger.warning("Unable to queue alert email delivery alert_id=%s", alert_id)


def create_alert(
    db_session: Session,
    *,
    user: User,
    monitor: Monitor,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    monitor_run_id: UUID | None = None,
    change_event_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Alert | None:
    preference = _get_preference(db_session, user_id=user.id, monitor_id=monitor.id)
    if preference is None:
        preference = _ensure_global_preference(db_session, user_id=user.id)

    if not preference.in_app_enabled:
        return None

    if not _passes_minimum_severity(
        minimum_event_severity=preference.minimum_event_severity,
        severity=severity,
    ):
        return None

    existing = _load_existing_alert(
        db_session,
        user_id=user.id,
        alert_type=alert_type,
        monitor_run_id=monitor_run_id,
        change_event_id=change_event_id,
    )
    if existing is not None:
        return existing

    provider = get_email_provider()
    if preference.email_enabled:
        delivery_status = "queued" if provider.name != "none" else "disabled"
        delivery_error = "email provider not configured" if provider.name == "none" else None
    else:
        delivery_status = "disabled"
        delivery_error = None

    alert = Alert(
        user_id=user.id,
        monitor_id=monitor.id,
        monitor_run_id=monitor_run_id,
        change_event_id=change_event_id,
        alert_type=alert_type,
        severity=("high" if severity == "critical" else severity),
        title=title,
        message=message,
        status="unread",
        delivery_status=delivery_status,
        delivery_error=delivery_error,
        metadata_=(metadata or {}),
    )

    try:
        db_session.add(alert)
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
        return _load_existing_alert(
            db_session,
            user_id=user.id,
            alert_type=alert_type,
            monitor_run_id=monitor_run_id,
            change_event_id=change_event_id,
        )
    except SQLAlchemyError as exc:
        raise AlertPersistenceError("Failed to persist alert") from exc

    if preference.email_enabled and provider.name != "none":
        _queue_alert_email(alert.id)

    return alert


def list_alerts(
    db_session: Session,
    *,
    user_id: UUID,
    limit: int,
    offset: int,
    unread_only: bool,
    monitor_id: UUID | None,
    alert_type: str | None,
) -> list[AlertRead]:
    try:
        statement: Select[tuple[Alert]] = select(Alert).where(Alert.user_id == user_id)
        if unread_only:
            statement = statement.where(Alert.status == "unread")
        if monitor_id is not None:
            statement = statement.where(Alert.monitor_id == monitor_id)
        if alert_type is not None:
            statement = statement.where(Alert.alert_type == alert_type)

        statement = statement.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).offset(offset)
        rows = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to list alerts") from exc

    return [_to_alert_read(row) for row in rows]


def get_alert(db_session: Session, *, user_id: UUID, alert_id: UUID) -> AlertRead | None:
    try:
        alert = db_session.execute(
            select(Alert).where(
                Alert.id == alert_id,
                Alert.user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to fetch alert") from exc

    if alert is None:
        return None
    return _to_alert_read(alert)


def update_alert_status(db_session: Session, *, user_id: UUID, alert_id: UUID, status: str) -> AlertRead | None:
    try:
        alert = db_session.execute(
            select(Alert).where(
                Alert.id == alert_id,
                Alert.user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to fetch alert") from exc

    if alert is None:
        return None

    alert.status = status
    if status == "read":
        alert.read_at = _utc_now()
    else:
        alert.read_at = None

    try:
        db_session.add(alert)
        db_session.commit()
        db_session.refresh(alert)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AlertPersistenceError("Failed to update alert") from exc

    return _to_alert_read(alert)


def get_notification_preference(
    db_session: Session,
    *,
    user_id: UUID,
    monitor_id: UUID | None,
) -> NotificationPreferenceRead:
    preference = _get_preference(db_session, user_id=user_id, monitor_id=monitor_id)
    if preference is None:
        preference = _ensure_global_preference(db_session, user_id=user_id)
        db_session.commit()
        db_session.refresh(preference)
    return _to_pref_read(preference)


def upsert_notification_preference(
    db_session: Session,
    *,
    user_id: UUID,
    monitor_id: UUID | None,
    request: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceRead:
    preference = _get_preference(db_session, user_id=user_id, monitor_id=monitor_id)
    if preference is None:
        preference = NotificationPreference(
            user_id=user_id,
            monitor_id=monitor_id,
            in_app_enabled=True,
            email_enabled=False,
            minimum_event_severity="low",
            minimum_semantic_confidence=None,
            notify_on_new_event=True,
            notify_on_failed_run=True,
            notify_on_partial_run=True,
        )

    patch = request.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(preference, key, value)

    try:
        db_session.add(preference)
        db_session.commit()
        db_session.refresh(preference)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AlertPersistenceError("Failed to save notification preference") from exc

    return _to_pref_read(preference)


def create_run_status_alert(
    db_session: Session,
    *,
    monitor: Monitor,
    run: MonitorRun,
    status: str,
    warnings: list[str] | None,
) -> None:
    if status not in {"partial", "failed"}:
        return

    owner = monitor.owner
    if owner is None:
        return

    preference = _get_preference(db_session, user_id=owner.id, monitor_id=monitor.id)
    if preference is None:
        preference = _ensure_global_preference(db_session, user_id=owner.id)

    if status == "failed" and not preference.notify_on_failed_run:
        return
    if status == "partial" and not preference.notify_on_partial_run:
        return

    alert_type = "run_failed" if status == "failed" else "run_partial"
    title = f"Monitor run {status}"
    message = f"ARGUS monitor run {run.id} for '{monitor.name}' completed with status '{status}'."
    metadata = {"warnings": warnings or []}

    create_alert(
        db_session,
        user=owner,
        monitor=monitor,
        alert_type=alert_type,
        severity="high" if status == "failed" else "medium",
        title=title,
        message=message,
        monitor_run_id=run.id,
        metadata=metadata,
    )


def create_change_event_alerts(
    db_session: Session,
    *,
    monitor: Monitor,
    run: MonitorRun,
    events: list[dict[str, Any]],
) -> None:
    owner = monitor.owner
    if owner is None:
        return

    preference = _get_preference(db_session, user_id=owner.id, monitor_id=monitor.id)
    if preference is None:
        preference = _ensure_global_preference(db_session, user_id=owner.id)

    for event in events:
        event_id = event.get("id")
        severity = str(event.get("severity") or "low").lower()
        confidence = event.get("confidence")

        if not isinstance(event_id, str):
            continue

        try:
            parsed_event_id = UUID(event_id)
        except ValueError:
            continue

        if preference.notify_on_new_event:
            create_alert(
                db_session,
                user=owner,
                monitor=monitor,
                alert_type="new_change_event",
                severity=severity,
                title="New change event detected",
                message=(
                    f"ARGUS detected a new observable land-surface change within monitor '{monitor.name}'."
                ),
                monitor_run_id=run.id,
                change_event_id=parsed_event_id,
                metadata={"confidence": confidence, "event_severity": severity},
            )

        if SEVERITY_ORDER.get(severity, 1) >= SEVERITY_ORDER["high"]:
            create_alert(
                db_session,
                user=owner,
                monitor=monitor,
                alert_type="high_change_evidence",
                severity="high",
                title="High change evidence",
                message=(
                    f"ARGUS detected high-confidence change evidence for monitor '{monitor.name}'."
                ),
                monitor_run_id=run.id,
                change_event_id=parsed_event_id,
                metadata={"confidence": confidence, "event_severity": severity},
            )


def _build_email_message(*, alert: Alert, user: User, monitor: Monitor) -> EmailMessage:
    subject = f"[ARGUS] {alert.title}"
    event_path = (
        f"/monitors/{monitor.id}?eventId={alert.change_event_id}"
        if alert.change_event_id is not None
        else f"/monitors/{monitor.id}"
    )

    text = "\n".join(
        [
            alert.title,
            "",
            alert.message,
            "",
            f"Monitor: {monitor.name}",
            f"Alert type: {alert.alert_type}",
            f"Severity: {alert.severity}",
            f"View in ARGUS: {event_path}",
            "",
            "A spatial intersection indicates overlap only; it does not by itself prove physical damage.",
        ]
    )
    html = (
        f"<h2>{alert.title}</h2>"
        f"<p>{alert.message}</p>"
        f"<p><strong>Monitor:</strong> {monitor.name}<br/>"
        f"<strong>Alert type:</strong> {alert.alert_type}<br/>"
        f"<strong>Severity:</strong> {alert.severity}</p>"
        f"<p><a href='{event_path}'>Open in ARGUS</a></p>"
        "<p><em>A spatial intersection indicates overlap only; it does not by itself prove physical damage.</em></p>"
    )

    return EmailMessage(to_email=user.email, subject=subject, text=text, html=html)


def deliver_alert_email(db_session: Session, *, alert_id: UUID) -> AlertRead | None:
    try:
        alert = db_session.execute(select(Alert).where(Alert.id == alert_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to fetch alert for email delivery") from exc

    if alert is None:
        return None

    if alert.delivery_status == "delivered":
        return _to_alert_read(alert)

    try:
        user = db_session.execute(select(User).where(User.id == alert.user_id)).scalar_one_or_none()
        monitor = db_session.execute(select(Monitor).where(Monitor.id == alert.monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AlertQueryError("Failed to fetch alert ownership records") from exc

    if user is None or monitor is None:
        return None

    provider = get_email_provider()
    if provider.name == "none":
        alert.delivery_status = "disabled"
        alert.delivery_error = "email provider not configured"
        try:
            db_session.add(alert)
            db_session.commit()
            db_session.refresh(alert)
        except SQLAlchemyError as exc:
            db_session.rollback()
            raise AlertPersistenceError("Failed to persist disabled email state") from exc
        return _to_alert_read(alert)

    email_message = _build_email_message(alert=alert, user=user, monitor=monitor)

    try:
        result = provider.send(email_message)
        if result.status == "delivered":
            alert.delivery_status = "delivered"
            alert.delivery_error = None
        elif result.status == "disabled":
            alert.delivery_status = "disabled"
            alert.delivery_error = result.error
        else:
            alert.delivery_status = "failed"
            alert.delivery_error = result.error or "unknown email delivery failure"

        db_session.add(alert)
        db_session.commit()
        db_session.refresh(alert)
    except EmailProviderError as exc:
        alert.delivery_status = "queued"
        alert.delivery_error = str(exc)
        db_session.add(alert)
        db_session.commit()
        raise AlertDeliveryError("Transient email provider error", retryable=exc.retryable) from exc
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AlertPersistenceError("Failed to persist email delivery result") from exc

    return _to_alert_read(alert)
