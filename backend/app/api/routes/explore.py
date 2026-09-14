from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas import ChangeEventRead, MonitorRead, MonitorRunRead, MonitorRunStatus
from app.services.change_event_service import ChangeEventQueryError, list_change_events
from app.services.monitor_service import MonitorQueryError, list_monitors
from app.services.monitoring_service import JobQueryError, list_monitor_runs

router = APIRouter(prefix="/explore", tags=["explore"])


EVENT_SEVERITY_VALUES = {"low", "medium", "high", "critical"}
EVENT_STATUS_VALUES = {"new", "reviewed", "dismissed", "confirmed"}


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_event_severity_filter(severity: str | None) -> str | None:
    normalized = _normalize_optional(severity)
    if normalized is None:
        return None
    if normalized not in EVENT_SEVERITY_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid severity filter")
    return normalized


def _normalize_event_status_filter(status_value: str | None) -> str | None:
    normalized = _normalize_optional(status_value)
    if normalized is None:
        return None
    if normalized not in EVENT_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status filter")
    return normalized


@router.get("/monitors", response_model=list[MonitorRead], status_code=status.HTTP_200_OK)
def list_public_monitors_route(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db_session: Session = Depends(get_db_session),
) -> list[MonitorRead]:
    try:
        return list_monitors(
            db_session,
            limit=limit,
            offset=offset,
            public_only=True,
        )
    except MonitorQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch public monitors") from exc


@router.get("/events", response_model=list[ChangeEventRead], status_code=status.HTTP_200_OK)
def list_public_events_route(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: str | None = Query(default=None),
    event_status: str | None = Query(default=None, alias="status"),
    db_session: Session = Depends(get_db_session),
) -> list[ChangeEventRead]:
    normalized_severity = _normalize_event_severity_filter(severity)
    normalized_status = _normalize_event_status_filter(event_status)

    try:
        monitors = list_monitors(
            db_session,
            limit=500,
            offset=0,
            public_only=True,
        )
    except MonitorQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch public monitors") from exc

    events: list[ChangeEventRead] = []
    for monitor in monitors:
        try:
            events.extend(
                list_change_events(
                    db_session,
                    monitor_id=monitor.id,
                    limit=200,
                    offset=0,
                    severity=normalized_severity,
                    status=normalized_status,
                    min_confidence=None,
                    min_area_m2=None,
                    analysis_id=None,
                    semantic_label=None,
                )
                or []
            )
        except ChangeEventQueryError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch public events") from exc

    ordered = sorted(events, key=lambda event: (event.first_detected_at, event.id), reverse=True)
    return ordered[offset : offset + limit]


@router.get("/runs", response_model=list[MonitorRunRead], status_code=status.HTTP_200_OK)
def list_public_runs_route(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    run_status: str | None = Query(default=None, alias="status"),
    db_session: Session = Depends(get_db_session),
) -> list[MonitorRunRead]:
    normalized_status: MonitorRunStatus | None = None
    normalized = _normalize_optional(run_status)
    if normalized is not None:
        try:
            normalized_status = MonitorRunStatus(normalized)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid run status filter") from exc

    try:
        monitors = list_monitors(
            db_session,
            limit=500,
            offset=0,
            public_only=True,
        )
    except MonitorQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch public monitors") from exc

    rows: list[MonitorRunRead] = []
    for monitor in monitors:
        try:
            runs = list_monitor_runs(
                db_session,
                monitor_id=monitor.id,
                limit=200,
                offset=0,
                status=normalized_status,
            )
            if runs is not None:
                rows.extend(runs)
        except JobQueryError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch public runs") from exc

    ordered = sorted(rows, key=lambda run: (run.started_at, run.id), reverse=True)
    return ordered[offset : offset + limit]
