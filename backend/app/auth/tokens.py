from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt

from app.core.config import get_settings


class TokenValidationError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode(payload: dict[str, Any]) -> str:
    settings = get_settings()
    return jwt.encode(payload, settings.argus_jwt_secret, algorithm="HS256")


def _decode(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.argus_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenValidationError("Invalid token") from exc

    if not isinstance(payload, dict):
        raise TokenValidationError("Invalid token payload")
    return payload


def create_access_token(*, user_id: UUID, role: str) -> tuple[str, datetime]:
    settings = get_settings()
    now = _utc_now()
    expires_at = now + timedelta(minutes=settings.argus_access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return _encode(payload), expires_at


def create_refresh_token(*, user_id: UUID, session_id: UUID, session_jti: UUID, expires_at: datetime) -> str:
    now = _utc_now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": str(session_jti),
        "typ": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return _encode(payload)


def decode_access_token(token: str) -> dict[str, Any]:
    payload = _decode(token)
    if payload.get("typ") != "access":
        raise TokenValidationError("Unexpected token type")
    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    payload = _decode(token)
    if payload.get("typ") != "refresh":
        raise TokenValidationError("Unexpected token type")

    try:
        UUID(str(payload.get("sid")))
        UUID(str(payload.get("jti")))
    except ValueError as exc:
        raise TokenValidationError("Invalid refresh token claims") from exc

    return payload
