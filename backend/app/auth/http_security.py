from __future__ import annotations

import re
import secrets
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.auth.tokens import TokenValidationError, decode_access_token
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, Monitor, User

PUBLIC_EXACT_PATHS = {
    "/",
    "/health",
    "/ready",
    "/worker/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}
PUBLIC_PREFIXES = (
    "/auth",
    "/explore",
)
MONITOR_PATH_PATTERN = re.compile(r"^/monitors/([0-9a-fA-F-]{36})(?:/|$)")
JOB_PATH_PATTERN = re.compile(r"^/jobs/([0-9a-fA-F-]{36})(?:/|$)")


def _json_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _parse_user_id(payload: dict[str, Any]) -> UUID:
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenValidationError("Invalid token subject")
    return UUID(subject)


def _get_monitor_owner_id(*, monitor_id: UUID) -> UUID | None:
    with SessionLocal() as db_session:
        return db_session.execute(
            select(Monitor.owner_user_id).where(Monitor.id == monitor_id)
        ).scalar_one_or_none()


def _get_job_owner_id(*, job_id: UUID) -> UUID | None:
    with SessionLocal() as db_session:
        return db_session.execute(
            select(Monitor.owner_user_id)
            .join(AnalysisJob, AnalysisJob.monitor_id == Monitor.id)
            .where(AnalysisJob.id == job_id)
        ).scalar_one_or_none()


def _csrf_valid(request: Any) -> bool:
    settings = get_settings()
    expected = request.cookies.get(settings.argus_csrf_cookie_name)
    supplied = request.headers.get("x-argus-csrf-token")
    if not expected or not supplied:
        return False
    return secrets.compare_digest(expected, supplied)


def authorize_request(request: Any) -> tuple[bool, JSONResponse | None, dict[str, Any] | None]:
    path = request.url.path
    if _is_public_path(path):
        return True, None, None

    settings = get_settings()
    access_token = request.cookies.get(settings.argus_access_cookie_name)
    if not access_token:
        return False, _json_error(401, "Authentication required"), None

    try:
        claims = decode_access_token(access_token)
        user_id = _parse_user_id(claims)
    except (TokenValidationError, ValueError):
        return False, _json_error(401, "Invalid or expired access token"), None

    with SessionLocal() as db_session:
        user = db_session.execute(
            select(User).where(User.id == user_id, User.is_active.is_(True))
        ).scalar_one_or_none()
        if user is None:
            return False, _json_error(401, "Authentication required"), None

        principal = {
            "id": str(user.id),
            "role": user.role,
        }

    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not path.startswith("/auth/") and not _csrf_valid(request):
            return False, _json_error(403, "Missing or invalid CSRF token"), None

    if path.startswith("/admin") and principal["role"] != "admin":
        return False, _json_error(403, "Admin access required"), None

    if principal["role"] != "admin":
        principal_user_id = UUID(principal["id"])

        monitor_match = MONITOR_PATH_PATTERN.match(path)
        if monitor_match:
            try:
                monitor_id = UUID(monitor_match.group(1))
            except ValueError:
                return False, _json_error(422, "Invalid monitor id"), None

            owner_user_id = _get_monitor_owner_id(monitor_id=monitor_id)
            if owner_user_id is not None and owner_user_id != principal_user_id:
                return False, _json_error(404, "Monitor not found"), None

        job_match = JOB_PATH_PATTERN.match(path)
        if job_match:
            try:
                job_id = UUID(job_match.group(1))
            except ValueError:
                return False, _json_error(422, "Invalid job id"), None

            owner_user_id = _get_job_owner_id(job_id=job_id)
            if owner_user_id is not None and owner_user_id != principal_user_id:
                return False, _json_error(404, "Analysis job not found"), None

    return True, None, principal
