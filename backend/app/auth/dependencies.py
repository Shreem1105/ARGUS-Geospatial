from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.tokens import TokenValidationError, decode_access_token
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models import User


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
    )


def _extract_access_token(request: Request) -> str | None:
    settings = get_settings()
    token = request.cookies.get(settings.argus_access_cookie_name)
    if token and token.strip():
        return token
    return None


def _load_user_from_token(db_session: Session, token: str) -> User | None:
    payload = decode_access_token(token)
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenValidationError("Invalid subject claim")

    user_id = UUID(subject)

    return db_session.execute(
        select(User).where(
            User.id == user_id,
            User.is_active.is_(True),
        )
    ).scalar_one_or_none()


def get_current_user_optional(
    request: Request,
    db_session: Session = Depends(get_db_session),
) -> User | None:
    token = _extract_access_token(request)
    if not token:
        return None

    try:
        return _load_user_from_token(db_session, token)
    except (TokenValidationError, ValueError, SQLAlchemyError):
        return None


def get_current_user(
    request: Request,
    db_session: Session = Depends(get_db_session),
) -> User:
    principal = getattr(request.state, "auth_principal", None)
    if isinstance(principal, dict):
        user_id_value = principal.get("id")
        if isinstance(user_id_value, str):
            try:
                user_id = UUID(user_id_value)
                user = db_session.execute(
                    select(User).where(User.id == user_id, User.is_active.is_(True))
                ).scalar_one_or_none()
                if user is not None:
                    return user
            except (ValueError, SQLAlchemyError):
                pass

    token = _extract_access_token(request)
    if not token:
        raise _unauthorized()

    try:
        user = _load_user_from_token(db_session, token)
    except ValueError as exc:
        raise _unauthorized("Invalid token subject") from exc
    except TokenValidationError as exc:
        raise _unauthorized("Invalid or expired access token") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to validate access token",
        ) from exc

    if user is None:
        raise _unauthorized()

    return user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def csrf_protect(request: Request) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return

    settings = get_settings()
    expected = request.cookies.get(settings.argus_csrf_cookie_name)
    supplied = request.headers.get("x-argus-csrf-token")

    if not expected or not supplied:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")

    if not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
