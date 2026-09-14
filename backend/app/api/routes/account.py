from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_protect, get_current_user
from app.db.session import get_db_session
from app.models import User
from app.schemas.account import (
    AccountQuotaRead,
    AccountUsageRead,
    NotificationPreferenceRead,
    NotificationPreferenceUpdateRequest,
)
from app.services.access_service import AccessQueryError, get_owned_monitor
from app.services.account_service import AccountQueryError, get_account_quota_for_user, get_account_usage_for_user
from app.services.alert_service import AlertPersistenceError, AlertQueryError, get_notification_preference, upsert_notification_preference

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/quota", response_model=AccountQuotaRead, status_code=status.HTTP_200_OK)
def get_account_quota_route(
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountQuotaRead:
    try:
        return get_account_quota_for_user(db_session, user=current_user)
    except AccountQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch account quota") from exc


@router.get("/usage", response_model=AccountUsageRead, status_code=status.HTTP_200_OK)
def get_account_usage_route(
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> AccountUsageRead:
    try:
        return get_account_usage_for_user(db_session, user=current_user)
    except AccountQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch account usage") from exc


def _ensure_monitor_owned_or_404(
    db_session: Session,
    *,
    monitor_id: UUID,
    user_id: UUID,
) -> None:
    try:
        monitor = get_owned_monitor(db_session, monitor_id=monitor_id, user_id=user_id)
    except AccessQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to validate monitor access") from exc

    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")


@router.get("/notifications/preferences", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
def get_notification_preference_route(
    monitor_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> NotificationPreferenceRead:
    if monitor_id is not None:
        _ensure_monitor_owned_or_404(db_session, monitor_id=monitor_id, user_id=current_user.id)

    try:
        return get_notification_preference(
            db_session,
            user_id=current_user.id,
            monitor_id=monitor_id,
        )
    except AlertQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch notification preference",
        ) from exc


@router.patch("/notifications/preferences", response_model=NotificationPreferenceRead, status_code=status.HTTP_200_OK)
def patch_notification_preference_route(
    payload: NotificationPreferenceUpdateRequest,
    request: Request,
    monitor_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> NotificationPreferenceRead:
    csrf_protect(request)
    if monitor_id is not None:
        _ensure_monitor_owned_or_404(db_session, monitor_id=monitor_id, user_id=current_user.id)

    try:
        return upsert_notification_preference(
            db_session,
            user_id=current_user.id,
            monitor_id=monitor_id,
            request=payload,
        )
    except (AlertPersistenceError, AlertQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save notification preference",
        ) from exc
