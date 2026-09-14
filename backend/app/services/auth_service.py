from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
)
from app.core.config import get_settings
from app.models import NotificationPreference, RefreshSession, User
from app.schemas.auth import AuthSessionRead, AuthUserRead, LoginRequest, RegisterRequest


class AuthConflictError(Exception):
    pass


class AuthCredentialsError(Exception):
    pass


class AuthTokenError(Exception):
    pass


class AuthPersistenceError(Exception):
    pass


@dataclass(slots=True)
class AuthSessionBundle:
    payload: AuthSessionRead
    access_token: str
    refresh_token: str


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _ip_hash(ip_address: str | None) -> str | None:
    if not ip_address:
        return None
    normalized = ip_address.strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _to_user_read(user: User) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _create_refresh_session(
    db_session: Session,
    *,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[RefreshSession, str, datetime]:
    settings = get_settings()
    expires_at = _utc_now() + timedelta(days=settings.argus_refresh_token_days)

    session_id = uuid4()
    session_jti = uuid4()
    refresh_token = create_refresh_token(
        user_id=user.id,
        session_id=session_id,
        session_jti=session_jti,
        expires_at=expires_at,
    )

    refresh_session = RefreshSession(
        id=session_id,
        user_id=user.id,
        jti=session_jti,
        token_hash=hash_token(refresh_token),
        expires_at=expires_at,
        user_agent=(user_agent[:512] if user_agent else None),
        ip_hash=_ip_hash(ip_address),
    )
    db_session.add(refresh_session)
    db_session.flush()

    return refresh_session, refresh_token, expires_at


def _build_session_bundle(
    db_session: Session,
    *,
    user: User,
    user_agent: str | None,
    ip_address: str | None,
    prior_refresh_session: RefreshSession | None = None,
) -> AuthSessionBundle:
    now = _utc_now()
    access_token, access_expires_at = create_access_token(user_id=user.id, role=user.role)
    refresh_session, refresh_token, refresh_expires_at = _create_refresh_session(
        db_session,
        user=user,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    if prior_refresh_session is not None:
        prior_refresh_session.revoked_at = now
        prior_refresh_session.replaced_by = refresh_session.id
        db_session.add(prior_refresh_session)

    csrf_token = secrets.token_urlsafe(32)
    payload = AuthSessionRead(
        user=_to_user_read(user),
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        csrf_token=csrf_token,
    )
    return AuthSessionBundle(
        payload=payload,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def register_user(
    db_session: Session,
    *,
    request: RegisterRequest,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthSessionBundle:
    user = User(
        email=_normalize_email(str(request.email)),
        password_hash=hash_password(request.password),
        display_name=request.display_name,
        role="user",
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)

    try:
        db_session.flush()
        db_session.add(
            NotificationPreference(
                user_id=user.id,
                monitor_id=None,
                in_app_enabled=True,
                email_enabled=False,
                minimum_event_severity="low",
                minimum_semantic_confidence=None,
                notify_on_new_event=True,
                notify_on_failed_run=True,
                notify_on_partial_run=True,
            )
        )

        bundle = _build_session_bundle(
            db_session,
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        user.last_login_at = _utc_now()
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    except IntegrityError as exc:
        db_session.rollback()
        raise AuthConflictError("Email already registered") from exc
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AuthPersistenceError("Failed to register user") from exc

    bundle.payload.user = _to_user_read(user)
    return bundle


def login_user(
    db_session: Session,
    *,
    request: LoginRequest,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthSessionBundle:
    email = _normalize_email(str(request.email))

    try:
        user = db_session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AuthPersistenceError("Failed to fetch user") from exc

    if user is None:
        raise AuthCredentialsError("Invalid credentials")

    if not user.is_active:
        raise AuthCredentialsError("Invalid credentials")

    if not verify_password(request.password, user.password_hash):
        raise AuthCredentialsError("Invalid credentials")

    try:
        user.last_login_at = _utc_now()
        bundle = _build_session_bundle(
            db_session,
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AuthPersistenceError("Failed to create login session") from exc

    bundle.payload.user = _to_user_read(user)
    return bundle


def refresh_login_session(
    db_session: Session,
    *,
    refresh_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthSessionBundle:
    try:
        claims = decode_refresh_token(refresh_token)
    except TokenValidationError as exc:
        raise AuthTokenError("Invalid refresh token") from exc

    try:
        session_id = UUID(str(claims["sid"]))
        user_id = UUID(str(claims["sub"]))
        token_jti = UUID(str(claims["jti"]))
    except (KeyError, ValueError) as exc:
        raise AuthTokenError("Invalid refresh token claims") from exc

    try:
        refresh_session = db_session.execute(
            select(RefreshSession).where(
                RefreshSession.id == session_id,
                RefreshSession.user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AuthPersistenceError("Failed to fetch refresh session") from exc

    if refresh_session is None:
        raise AuthTokenError("Refresh session not found")

    now = _utc_now()
    if refresh_session.revoked_at is not None or refresh_session.expires_at <= now:
        raise AuthTokenError("Refresh session expired or revoked")

    if refresh_session.jti != token_jti:
        refresh_session.revoked_at = now
        db_session.add(refresh_session)
        db_session.commit()
        raise AuthTokenError("Refresh session invalidated")

    expected_hash = refresh_session.token_hash
    supplied_hash = hash_token(refresh_token)
    if not secrets.compare_digest(expected_hash, supplied_hash):
        refresh_session.revoked_at = now
        db_session.add(refresh_session)
        db_session.commit()
        raise AuthTokenError("Refresh token mismatch")

    try:
        user = db_session.execute(
            select(User).where(
                User.id == refresh_session.user_id,
                User.is_active.is_(True),
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AuthPersistenceError("Failed to fetch session user") from exc

    if user is None:
        raise AuthTokenError("Refresh session user unavailable")

    try:
        bundle = _build_session_bundle(
            db_session,
            user=user,
            user_agent=user_agent,
            ip_address=ip_address,
            prior_refresh_session=refresh_session,
        )
        db_session.commit()
        db_session.refresh(user)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AuthPersistenceError("Failed to rotate refresh session") from exc

    bundle.payload.user = _to_user_read(user)
    return bundle


def revoke_refresh_session(db_session: Session, *, refresh_token: str | None) -> bool:
    if refresh_token is None:
        return False

    try:
        claims = decode_refresh_token(refresh_token)
        session_id = UUID(str(claims["sid"]))
        user_id = UUID(str(claims["sub"]))
    except (TokenValidationError, KeyError, ValueError):
        return False

    try:
        refresh_session = db_session.execute(
            select(RefreshSession).where(
                RefreshSession.id == session_id,
                RefreshSession.user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AuthPersistenceError("Failed to fetch refresh session") from exc

    if refresh_session is None:
        return False

    if refresh_session.revoked_at is not None:
        return True

    refresh_session.revoked_at = _utc_now()
    try:
        db_session.add(refresh_session)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AuthPersistenceError("Failed to revoke refresh session") from exc

    return True


def revoke_all_refresh_sessions(db_session: Session, *, user_id: UUID) -> int:
    now = _utc_now()
    try:
        sessions = db_session.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        ).scalars().all()

        for session in sessions:
            session.revoked_at = now
            db_session.add(session)

        db_session.commit()
        return len(sessions)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise AuthPersistenceError("Failed to revoke sessions") from exc
