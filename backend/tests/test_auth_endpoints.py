from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.tokens import hash_token
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import RefreshSession, User


DEFAULT_PASSWORD = "StrongerPass!234"


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_user_ids() -> Generator[list[UUID], None, None]:
    user_ids: list[UUID] = []
    yield user_ids

    if not user_ids:
        return

    with SessionLocal() as db_session:
        db_session.execute(delete(User).where(User.id.in_(user_ids)))
        db_session.commit()


def _new_email() -> str:
    return f"auth-{uuid4().hex}@example.com"


def _register(
    client: TestClient,
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Auth User",
) -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_register_success_persists_user_without_leaking_sensitive_fields(
    client: TestClient,
    created_user_ids: list[UUID],
) -> None:
    payload = _register(client, email="Mixed.Case+Auth@Example.COM", password=DEFAULT_PASSWORD)
    user = payload["user"]
    user_id = UUID(str(user["id"]))
    created_user_ids.append(user_id)

    assert user["email"] == "mixed.case+auth@example.com"
    assert "password" not in user
    assert "password_hash" not in user
    assert DEFAULT_PASSWORD not in str(payload)

    settings = get_settings()
    refresh_token = client.cookies.get(settings.argus_refresh_cookie_name)
    assert isinstance(refresh_token, str) and refresh_token

    with SessionLocal() as db_session:
        stored_user = db_session.execute(select(User).where(User.id == user_id)).scalar_one()
        assert stored_user.password_hash.startswith("$argon2")
        assert stored_user.password_hash != DEFAULT_PASSWORD

        refresh_session = db_session.execute(
            select(RefreshSession)
            .where(RefreshSession.user_id == user_id)
            .order_by(RefreshSession.created_at.desc())
        ).scalar_one()
        assert refresh_session.token_hash == hash_token(refresh_token)
        assert refresh_session.token_hash != refresh_token


def test_register_duplicate_email_conflict(client: TestClient, created_user_ids: list[UUID]) -> None:
    email = _new_email()
    first = _register(client, email=email)
    created_user_ids.append(UUID(str(first["user"]["id"])))

    duplicate = client.post(
        "/auth/register",
        json={"email": email.upper(), "password": DEFAULT_PASSWORD, "display_name": "Duplicate"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Email is already registered"


def test_login_success_and_wrong_password(client: TestClient, created_user_ids: list[UUID]) -> None:
    email = _new_email()
    created = _register(client, email=email)
    created_user_ids.append(UUID(str(created["user"]["id"])))

    ok = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == email

    wrong = client.post("/auth/login", json={"email": email, "password": "wrong-password-value"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Invalid credentials"


def test_login_rejects_inactive_user(client: TestClient, created_user_ids: list[UUID]) -> None:
    email = _new_email()
    created = _register(client, email=email)
    user_id = UUID(str(created["user"]["id"]))
    created_user_ids.append(user_id)

    with SessionLocal() as db_session:
        user = db_session.execute(select(User).where(User.id == user_id)).scalar_one()
        user.is_active = False
        db_session.add(user)
        db_session.commit()

    response = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_auth_me_requires_valid_access_token(client: TestClient, created_user_ids: list[UUID]) -> None:
    created = _register(client, email=_new_email())
    user_id = UUID(str(created["user"]["id"]))
    created_user_ids.append(user_id)

    valid_me = client.get("/auth/me")
    assert valid_me.status_code == 200
    assert valid_me.json()["id"] == str(user_id)

    settings = get_settings()
    client.cookies.delete(settings.argus_access_cookie_name, path="/")

    missing = client.get("/auth/me", headers={"x-argus-test-no-auto-auth": "1"})
    assert missing.status_code == 401

    client.cookies.set(settings.argus_access_cookie_name, "not-a-jwt", path="/")
    invalid = client.get("/auth/me")
    assert invalid.status_code == 401


@pytest.mark.usefixtures("client")
def test_expired_access_token_is_rejected(client: TestClient, created_user_ids: list[UUID]) -> None:
    created = _register(client, email=_new_email())
    user_id = UUID(str(created["user"]["id"]))
    created_user_ids.append(user_id)

    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    expired = jwt.encode(
        {
            "sub": str(user_id),
            "role": "user",
            "typ": "access",
            "iat": int((now - timedelta(minutes=10)).timestamp()),
            "exp": int((now - timedelta(minutes=1)).timestamp()),
        },
        settings.argus_jwt_secret,
        algorithm="HS256",
    )

    client.cookies.set(settings.argus_access_cookie_name, expired, path="/")
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired access token"


def test_refresh_success_rotation_and_old_token_reuse_rejected(
    client: TestClient,
    created_user_ids: list[UUID],
) -> None:
    created = _register(client, email=_new_email())
    user_id = UUID(str(created["user"]["id"]))
    created_user_ids.append(user_id)

    settings = get_settings()
    first_refresh_token = client.cookies.get(settings.argus_refresh_cookie_name)
    csrf_token = client.cookies.get(settings.argus_csrf_cookie_name)
    assert isinstance(first_refresh_token, str) and first_refresh_token
    assert isinstance(csrf_token, str) and csrf_token

    refresh_response = client.post("/auth/refresh", headers={"x-argus-csrf-token": csrf_token})
    assert refresh_response.status_code == 200
    second_refresh_token = client.cookies.get(settings.argus_refresh_cookie_name)
    assert isinstance(second_refresh_token, str) and second_refresh_token
    assert second_refresh_token != first_refresh_token

    with SessionLocal() as db_session:
        first_session = db_session.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.token_hash == hash_token(first_refresh_token),
            )
        ).scalar_one()
        assert first_session.revoked_at is not None

    client.cookies.set(settings.argus_refresh_cookie_name, first_refresh_token, path="/")
    rotated_csrf_token = client.cookies.get(settings.argus_csrf_cookie_name)
    reuse = client.post("/auth/refresh", headers={"x-argus-csrf-token": rotated_csrf_token})
    assert reuse.status_code == 401
    assert reuse.json()["detail"] == "Invalid refresh token"


def test_refresh_and_logout_require_csrf(client: TestClient, created_user_ids: list[UUID]) -> None:
    created = _register(client, email=_new_email())
    created_user_ids.append(UUID(str(created["user"]["id"])))

    refresh_without_csrf = client.post("/auth/refresh")
    assert refresh_without_csrf.status_code == 403

    logout_without_csrf = client.post("/auth/logout")
    assert logout_without_csrf.status_code == 403


def test_logout_revokes_refresh_session(client: TestClient, created_user_ids: list[UUID]) -> None:
    created = _register(client, email=_new_email())
    user_id = UUID(str(created["user"]["id"]))
    created_user_ids.append(user_id)

    settings = get_settings()
    refresh_token = client.cookies.get(settings.argus_refresh_cookie_name)
    csrf_token = client.cookies.get(settings.argus_csrf_cookie_name)

    response = client.post("/auth/logout", headers={"x-argus-csrf-token": csrf_token})
    assert response.status_code == 200
    assert response.json() == {"logged_out": True}

    with SessionLocal() as db_session:
        session = db_session.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.token_hash == hash_token(str(refresh_token)),
            )
        ).scalar_one()
        assert session.revoked_at is not None


def test_logout_all_revokes_every_session(created_user_ids: list[UUID]) -> None:
    email = _new_email()

    with TestClient(app) as client_a:
        created = _register(client_a, email=email)
        user_id = UUID(str(created["user"]["id"]))
        created_user_ids.append(user_id)

        with TestClient(app) as client_b:
            login_b = client_b.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD})
            assert login_b.status_code == 200

        csrf_token = client_a.cookies.get(get_settings().argus_csrf_cookie_name)
        response = client_a.post("/auth/logout-all", headers={"x-argus-csrf-token": csrf_token})
        assert response.status_code == 200

    with SessionLocal() as db_session:
        sessions = db_session.execute(select(RefreshSession).where(RefreshSession.user_id == user_id)).scalars().all()
        assert len(sessions) >= 2
        assert all(session.revoked_at is not None for session in sessions)


def test_refresh_with_invalid_token_returns_401(client: TestClient, created_user_ids: list[UUID]) -> None:
    created = _register(client, email=_new_email())
    created_user_ids.append(UUID(str(created["user"]["id"])))

    settings = get_settings()
    csrf_token = client.cookies.get(settings.argus_csrf_cookie_name)
    client.cookies.set(settings.argus_refresh_cookie_name, "invalid-refresh-token", path="/")

    response = client.post("/auth/refresh", headers={"x-argus-csrf-token": csrf_token})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"
