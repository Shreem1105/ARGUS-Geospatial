from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_protect, require_admin_user
from app.db.session import get_db_session
from app.models import User
from app.schemas.account import AccountQuotaRead, AdminUserRead, UserQuotaOverrideWrite
from app.services.account_service import (
    AccountPersistenceError,
    AccountQueryError,
    get_account_quota_for_user,
    get_user,
    list_users,
    upsert_user_quota_override,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserRead], status_code=status.HTTP_200_OK)
def list_users_route(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin_user),
    db_session: Session = Depends(get_db_session),
) -> list[AdminUserRead]:
    try:
        return list_users(db_session, limit=limit, offset=offset)
    except AccountQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to list users") from exc


@router.get("/users/{user_id}/quota", response_model=AccountQuotaRead, status_code=status.HTTP_200_OK)
def get_user_quota_route(
    user_id: UUID,
    _: User = Depends(require_admin_user),
    db_session: Session = Depends(get_db_session),
) -> AccountQuotaRead:
    try:
        user = get_user(db_session, user_id=user_id)
    except AccountQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch user") from exc

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return get_account_quota_for_user(db_session, user=user)


@router.patch("/users/{user_id}/quota", response_model=AccountQuotaRead, status_code=status.HTTP_200_OK)
def patch_user_quota_route(
    user_id: UUID,
    payload: UserQuotaOverrideWrite,
    request: Request,
    _: User = Depends(require_admin_user),
    db_session: Session = Depends(get_db_session),
) -> AccountQuotaRead:
    csrf_protect(request)

    try:
        user = get_user(db_session, user_id=user_id)
    except AccountQueryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to fetch user") from exc

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        upsert_user_quota_override(db_session, user_id=user_id, request=payload)
    except (AccountPersistenceError, AccountQueryError) as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to update quota") from exc

    return get_account_quota_for_user(db_session, user=user)
