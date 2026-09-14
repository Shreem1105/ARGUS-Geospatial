from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_protect, get_current_user
from app.db.session import get_db_session
from app.models import Alert, User
from app.schemas.alert import AlertListResponse, AlertRead, AlertUpdateRequest
from app.services.alert_service import AlertPersistenceError, AlertQueryError, get_alert, list_alerts, update_alert_status

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse, status_code=status.HTTP_200_OK)
def list_alerts_route(
    unread_only: bool = Query(default=False),
    monitor_id: UUID | None = Query(default=None),
    alert_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AlertListResponse:
    try:
        rows = list_alerts(
            db_session,
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            unread_only=unread_only,
            monitor_id=monitor_id,
            alert_type=alert_type,
        )
    except AlertQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch alerts") from exc

    return AlertListResponse(count=len(rows), alerts=rows)


@router.get("/{alert_id}", response_model=AlertRead, status_code=status.HTTP_200_OK)
def get_alert_route(
    alert_id: UUID,
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AlertRead:
    try:
        alert = get_alert(db_session, user_id=current_user.id, alert_id=alert_id)
    except AlertQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch alert") from exc

    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    return alert


@router.patch("/{alert_id}", response_model=AlertRead, status_code=status.HTTP_200_OK)
def patch_alert_route(
    alert_id: UUID,
    payload: AlertUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AlertRead:
    csrf_protect(request)
    try:
        alert = update_alert_status(
            db_session,
            user_id=current_user.id,
            alert_id=alert_id,
            status=payload.status,
        )
    except (AlertQueryError, AlertPersistenceError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to update alert") from exc

    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    return alert


@router.post("/read-all", response_model=AlertListResponse, status_code=status.HTTP_200_OK)
def mark_all_alerts_read_route(
    request: Request,
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AlertListResponse:
    csrf_protect(request)
    try:
        db_session.execute(
            update(Alert)
            .where(
                Alert.user_id == current_user.id,
                Alert.status == "unread",
            )
            .values(status="read", read_at=func.now())
        )
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to mark alerts read") from exc

    try:
        rows = list_alerts(
            db_session,
            user_id=current_user.id,
            limit=50,
            offset=0,
            unread_only=False,
            monitor_id=None,
            alert_type=None,
        )
    except AlertQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch alerts") from exc

    return AlertListResponse(count=len(rows), alerts=rows)
