from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import csrf_protect, get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models import User
from app.schemas.auth import AuthSessionRead, AuthUserRead, LoginRequest, LogoutResponse, RegisterRequest
from app.services.auth_service import (
    AuthConflictError,
    AuthCredentialsError,
    AuthPersistenceError,
    AuthTokenError,
    login_user,
    refresh_login_session,
    register_user,
    revoke_all_refresh_sessions,
    revoke_refresh_session,
)
from app.services.rate_limit_service import RateLimitExceededError, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _seconds_until(expires_at: datetime) -> int:
    now = datetime.now(tz=timezone.utc)
    delta_seconds = int((expires_at - now).total_seconds())
    return max(1, delta_seconds)


def _set_auth_cookies(response: Response, *, payload: AuthSessionRead, access_token: str, refresh_token: str) -> None:
    settings = get_settings()

    cookie_kwargs = {
        "httponly": True,
        "secure": settings.argus_cookie_secure,
        "samesite": settings.argus_cookie_samesite,
        "path": "/",
    }

    if settings.argus_cookie_domain:
        cookie_kwargs["domain"] = settings.argus_cookie_domain

    response.set_cookie(
        key=settings.argus_access_cookie_name,
        value=access_token,
        max_age=_seconds_until(payload.access_token_expires_at),
        **cookie_kwargs,
    )
    response.set_cookie(
        key=settings.argus_refresh_cookie_name,
        value=refresh_token,
        max_age=_seconds_until(payload.refresh_token_expires_at),
        **cookie_kwargs,
    )
    response.set_cookie(
        key=settings.argus_csrf_cookie_name,
        value=payload.csrf_token,
        httponly=False,
        secure=settings.argus_cookie_secure,
        samesite=settings.argus_cookie_samesite,
        path="/",
        max_age=_seconds_until(payload.refresh_token_expires_at),
        domain=settings.argus_cookie_domain,
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()

    for key in [
        settings.argus_access_cookie_name,
        settings.argus_refresh_cookie_name,
        settings.argus_csrf_cookie_name,
    ]:
        response.delete_cookie(
            key=key,
            domain=settings.argus_cookie_domain,
            path="/",
        )


def _rate_limit_or_raise(*, request: Request, scope: str, limit: int, window_seconds: int) -> None:
    client_host = request.client.host if request.client else "unknown"
    try:
        enforce_rate_limit(
            key_id=client_host,
            scope=scope,
            limit=limit,
            window_seconds=window_seconds,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "scope": exc.scope,
                "limit": exc.limit,
                "window_seconds": exc.window_seconds,
                "retry_after_seconds": exc.retry_after_seconds,
            },
        ) from exc


@router.post("/register", response_model=AuthSessionRead, status_code=status.HTTP_201_CREATED)
def register_route(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    db_session: Session = Depends(get_db_session),
) -> AuthSessionRead:
    settings = get_settings()
    _rate_limit_or_raise(
        request=request,
        scope="auth_register",
        limit=settings.rate_limit_register_per_hour,
        window_seconds=3600,
    )

    try:
        session = register_user(
            db_session,
            request=payload,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except AuthConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered") from exc
    except AuthPersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to register") from exc

    _set_auth_cookies(
        response,
        payload=session.payload,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )
    return session.payload


@router.post("/login", response_model=AuthSessionRead, status_code=status.HTTP_200_OK)
def login_route(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db_session: Session = Depends(get_db_session),
) -> AuthSessionRead:
    settings = get_settings()
    _rate_limit_or_raise(
        request=request,
        scope="auth_login",
        limit=settings.rate_limit_login_per_minute,
        window_seconds=60,
    )

    try:
        session = login_user(
            db_session,
            request=payload,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except AuthCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from exc
    except AuthPersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to login") from exc

    _set_auth_cookies(
        response,
        payload=session.payload,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )
    return session.payload


@router.post("/refresh", response_model=AuthSessionRead, status_code=status.HTTP_200_OK)
def refresh_route(
    request: Request,
    response: Response,
    db_session: Session = Depends(get_db_session),
) -> AuthSessionRead:
    settings = get_settings()
    _rate_limit_or_raise(
        request=request,
        scope="auth_refresh",
        limit=settings.rate_limit_refresh_per_minute,
        window_seconds=60,
    )

    csrf_protect(request)
    refresh_token = request.cookies.get(settings.argus_refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    try:
        session = refresh_login_session(
            db_session,
            refresh_token=refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except AuthTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    except AuthPersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to refresh session") from exc

    _set_auth_cookies(
        response,
        payload=session.payload,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
    )
    return session.payload


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout_route(
    request: Request,
    response: Response,
    db_session: Session = Depends(get_db_session),
) -> LogoutResponse:
    csrf_protect(request)
    settings = get_settings()
    refresh_token = request.cookies.get(settings.argus_refresh_cookie_name)

    try:
        revoke_refresh_session(db_session, refresh_token=refresh_token)
    except AuthPersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to logout") from exc

    _clear_auth_cookies(response)
    return LogoutResponse(logged_out=True)


@router.post("/logout-all", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout_all_route(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db_session: Session = Depends(get_db_session),
) -> LogoutResponse:
    csrf_protect(request)
    try:
        revoke_all_refresh_sessions(db_session, user_id=current_user.id)
    except AuthPersistenceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to logout all sessions") from exc

    _clear_auth_cookies(response)
    return LogoutResponse(logged_out=True)


@router.get("/me", response_model=AuthUserRead, status_code=status.HTTP_200_OK)
def me_route(current_user: User = Depends(get_current_user)) -> AuthUserRead:
    return AuthUserRead(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        last_login_at=current_user.last_login_at,
    )
