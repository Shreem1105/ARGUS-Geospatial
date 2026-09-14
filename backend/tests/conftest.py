from __future__ import annotations

import secrets
import threading
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.tokens import create_access_token
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import NotificationPreference, UsageEvent, User, UserQuota

TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_EMAIL = "system@argus.local"
TEST_USER_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$ube2FoKQ8h4jhHCOEaJUSg$S1d1Qfe49OJ/oCQaleLUrHHdkRgrorYcaS9QKI0AZis"
)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_AUTH_LOCK = threading.Lock()
_SKIP_AUTO_AUTH_HEADER = "x-argus-test-no-auto-auth"


class _InMemoryRateLimitRedis:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._expires_at: dict[str, float] = {}

    def _prune(self, key: str) -> None:
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return

        if time.time() >= expires_at:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)

    def incr(self, key: str) -> int:
        self._prune(key)
        value = int(self._values.get(key, 0)) + 1
        self._values[key] = value
        return value

    def expire(self, key: str, ttl_seconds: int) -> bool:
        self._expires_at[key] = time.time() + max(1, int(ttl_seconds))
        return True


def _ensure_test_user() -> tuple[UUID, str]:
    with SessionLocal() as db_session:
        try:
            user = db_session.execute(
                select(User).where(User.id == TEST_USER_ID)
            ).scalar_one_or_none()

            if user is None:
                user = User(
                    id=TEST_USER_ID,
                    email=TEST_USER_EMAIL,
                    password_hash=TEST_USER_PASSWORD_HASH,
                    display_name="ARGUS System",
                    role="user",
                    is_active=True,
                    is_verified=False,
                )
                db_session.add(user)
                db_session.flush()
            else:
                user.email = TEST_USER_EMAIL
                user.password_hash = TEST_USER_PASSWORD_HASH
                user.display_name = "ARGUS System"
                user.role = "user"
                user.is_active = True

            global_pref = db_session.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == TEST_USER_ID,
                    NotificationPreference.monitor_id.is_(None),
                )
            ).scalar_one_or_none()

            if global_pref is None:
                db_session.add(
                    NotificationPreference(
                        user_id=TEST_USER_ID,
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

            quota = db_session.execute(
                select(UserQuota).where(UserQuota.user_id == TEST_USER_ID)
            ).scalar_one_or_none()
            if quota is None:
                quota = UserQuota(user_id=TEST_USER_ID)

            quota.max_monitors = 100000
            quota.max_active_monitors = 100000
            quota.max_aoi_area_km2 = 1_000_000.0
            quota.max_manual_runs_per_day = 100000
            quota.max_observation_searches_per_day = 100000
            quota.max_semantic_runs_per_day = 100000
            quota.max_concurrent_jobs = 100000
            db_session.add(quota)

            db_session.execute(delete(UsageEvent).where(UsageEvent.user_id == TEST_USER_ID))

            db_session.commit()
            return user.id, user.role
        except SQLAlchemyError:
            db_session.rollback()
            raise


def _client_has_auth(client: TestClient) -> bool:
    if bool(getattr(client, "_argus_test_auth_ready", False)):
        return True

    settings = get_settings()
    token = client.cookies.get(settings.argus_access_cookie_name)
    return bool(token and str(token).strip())


def _set_client_auth(client: TestClient) -> None:
    if _client_has_auth(client):
        return

    with _AUTH_LOCK:
        if _client_has_auth(client):
            return

        user_id, role = _ensure_test_user()
        access_token, _ = create_access_token(user_id=user_id, role=role)
        csrf_token = secrets.token_urlsafe(32)

        settings = get_settings()
        client.cookies.set(settings.argus_access_cookie_name, access_token, path="/")
        client.cookies.set(settings.argus_csrf_cookie_name, csrf_token, path="/")
        client.cookies.set(settings.argus_refresh_cookie_name, "pytest-refresh-placeholder", path="/")

        setattr(client, "_argus_test_auth_ready", True)
        setattr(client, "_argus_test_csrf", csrf_token)


def _is_auth_endpoint(url: str) -> bool:
    normalized = url.split("?", 1)[0]
    return normalized.startswith("/auth")


@pytest.fixture(scope="session", autouse=True)
def _patch_testclient_with_auth() -> None:
    original_request = TestClient.request

    def patched_request(self: TestClient, method: str, url: str, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        skip_auto_auth_value = headers.pop(_SKIP_AUTO_AUTH_HEADER, None)
        skip_auto_auth = str(skip_auto_auth_value).strip().lower() in {"1", "true", "yes"}

        if headers:
            kwargs["headers"] = headers
        else:
            kwargs.pop("headers", None)

        if not skip_auto_auth and not _is_auth_endpoint(url):
            _set_client_auth(self)

        if method.upper() not in _SAFE_METHODS and not _is_auth_endpoint(url) and not skip_auto_auth:
            headers = dict(kwargs.get("headers") or {})
            if not any(key.lower() == "x-argus-csrf-token" for key in headers):
                settings = get_settings()
                csrf_cookie = self.cookies.get(settings.argus_csrf_cookie_name)
                headers["x-argus-csrf-token"] = csrf_cookie or getattr(self, "_argus_test_csrf", "")
            kwargs["headers"] = headers

        return original_request(self, method, url, *args, **kwargs)

    TestClient.request = patched_request
    try:
        yield
    finally:
        TestClient.request = original_request


@pytest.fixture(autouse=True)
def _use_in_memory_rate_limit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.rate_limit_service as rate_limit_service

    redis_backend = _InMemoryRateLimitRedis()
    monkeypatch.setattr(rate_limit_service, "_redis_client", lambda: redis_backend)