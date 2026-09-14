from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import User, UserQuota
from app.schemas.account import AdminUserRead, UserQuotaOverrideWrite
from app.services.quota_service import build_account_quota, build_account_usage


class AccountQueryError(Exception):
    pass


class AccountPersistenceError(Exception):
    pass


def _to_admin_user_read(user: User) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def list_users(db_session: Session, *, limit: int, offset: int) -> list[AdminUserRead]:
    try:
        rows = db_session.execute(
            select(User)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise AccountQueryError("Failed to list users") from exc

    return [_to_admin_user_read(user) for user in rows]


def get_user(db_session: Session, *, user_id: UUID) -> User | None:
    try:
        return db_session.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AccountQueryError("Failed to fetch user") from exc


def get_account_quota_for_user(db_session: Session, *, user: User):
    return build_account_quota(db_session, user=user)


def get_account_usage_for_user(db_session: Session, *, user: User):
    return build_account_usage(db_session, user=user)


def upsert_user_quota_override(
    db_session: Session,
    *,
    user_id: UUID,
    request: UserQuotaOverrideWrite,
) -> UserQuota:
    try:
        quota = db_session.execute(select(UserQuota).where(UserQuota.user_id == user_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AccountQueryError("Failed to fetch quota override") from exc

    if quota is None:
        quota = UserQuota(user_id=user_id)

    for key, value in request.model_dump(exclude_unset=True).items():
        setattr(quota, key, value)

    try:
        db_session.add(quota)
        db_session.commit()
        db_session.refresh(quota)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AccountPersistenceError("Failed to save quota override") from exc

    return quota
