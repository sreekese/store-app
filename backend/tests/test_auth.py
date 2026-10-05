from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, RefreshToken, Role, User
from app.auth.security import hash_password, token_hash, verify_password
from app.core.config import Settings

SECRET = "test-only-signing-key-not-a-production-secret-123"
PASSWORD = "Correct-Horse-Local-2026"
HEADERS = {"X-CSRF-Protection": "1", "Origin": "http://localhost:5173"}
pytestmark = pytest.mark.integration


def create_user(client: TestClient, role: Role = Role.USER) -> User:
    with Session(client.app.state.engine) as db:
        user = User(
            email=f"{uuid4().hex}@example.com",
            display_name="Test account",
            role=role,
            password_hash=hash_password(PASSWORD),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def login(client: TestClient, user: User, **overrides: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "workspace": user.role, **overrides},
    )


def bearer(response) -> dict[str, str]:
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_registration_hashes_password_and_normalizes_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "Shopper@Example.com", "display_name": "Ananya", "password": PASSWORD},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "USER"
    assert "password" not in response.text and "hash" not in response.text
    with Session(client.app.state.engine) as db:
        user = db.scalar(select(User).where(User.email == "shopper@example.com"))
        assert user and user.password_hash.startswith("$argon2id$")
        assert verify_password(PASSWORD, user.password_hash)


@pytest.mark.parametrize("role", ["ADMIN", "SUPER_ADMIN", "MERCHANT_STAFF"])
def test_registration_cannot_escalate_role(client: TestClient, role: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "display_name": "New",
            "password": PASSWORD,
            "role": role,
        },
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(User.id)) is None


def test_merchant_registration_and_duplicate_email(client: TestClient) -> None:
    data = {
        "email": "owner@example.com",
        "password": PASSWORD,
        "display_name": "Store owner",
        "role": "MERCHANT",
    }
    assert client.post("/api/v1/auth/register", json=data).status_code == 201
    assert client.post("/api/v1/auth/register", json=data).status_code == 409


def test_password_validation_does_not_echo_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "display_name": "New", "password": "shortSecret"},
    )
    assert response.status_code == 422 and "shortSecret" not in response.text


def test_login_and_current_user_cookie_security(client: TestClient) -> None:
    user = create_user(client)
    result = login(client, user)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1/auth" in cookie
    response = client.get("/api/v1/auth/me", headers=bearer(result))
    assert response.status_code == 200 and response.json()["id"] == str(user.id)
    assert "password_hash" not in response.json()
    raw = client.cookies.get("nearperk_refresh")
    with Session(client.app.state.engine) as db:
        assert db.get(RefreshToken, token_hash(raw)) is not None
        assert db.get(RefreshToken, raw) is None


def test_unknown_wrong_password_wrong_role_same_error(client: TestClient) -> None:
    user = create_user(client)
    outcomes = [
        login(client, user, password="wrong"),
        login(client, user, email="absent@example.com"),
        login(client, user, workspace="SUPER_ADMIN"),
    ]
    assert {r.status_code for r in outcomes} == {401}
    assert len({r.json()["error"]["message"] for r in outcomes}) == 1


@pytest.mark.parametrize(
    "role,path",
    [
        (Role.USER, "shopper"),
        (Role.MERCHANT, "merchant"),
        (Role.MERCHANT_STAFF, "staff"),
        (Role.ADMIN, "admin"),
        (Role.SUPER_ADMIN, "superadmin"),
    ],
)
def test_workspace_permissions_are_server_enforced(
    client: TestClient, role: Role, path: str
) -> None:
    user = create_user(client, role)
    headers = bearer(login(client, user))
    assert client.get(f"/api/v1/workspaces/{path}", headers=headers).status_code == 200
    for other in ("shopper", "merchant", "staff", "admin", "superadmin"):
        expected = 200 if other == path or (role == Role.SUPER_ADMIN and other == "admin") else 403
        assert client.get(f"/api/v1/workspaces/{other}", headers=headers).status_code == expected


def test_anonymous_cannot_read_private_apis(client: TestClient) -> None:
    for path in ("/auth/me", "/workspaces/merchant", "/workspaces/staff", "/workspaces/superadmin"):
        assert client.get("/api/v1" + path).status_code == 401


def test_refresh_rotates_and_replay_revokes_entire_session(client: TestClient) -> None:
    result = login(client, create_user(client))
    old = client.cookies.get("nearperk_refresh")
    rotated = client.post("/api/v1/auth/refresh")
    new = client.cookies.get("nearperk_refresh")
    assert rotated.status_code == 200 and new != old
    assert client.get("/api/v1/auth/me", headers=bearer(result)).status_code == 200
    client.cookies.clear()
    replay = client.post("/api/v1/auth/refresh", headers={"Cookie": f"nearperk_refresh={old}"})
    assert replay.status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(rotated)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"Cookie": f"nearperk_refresh={new}"}
        ).status_code
        == 401
    )


def test_logout_immediately_revokes_access_and_refresh(client: TestClient) -> None:
    result = login(client, create_user(client))
    raw = client.cookies.get("nearperk_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.cookies.get("nearperk_refresh") is None
    assert client.get("/api/v1/auth/me", headers=bearer(result)).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", headers={"Cookie": f"nearperk_refresh={raw}"}
        ).status_code
        == 401
    )
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_other_device_session_survives_logout(client: TestClient) -> None:
    user = create_user(client)
    first = login(client, user)
    second = login(client, user)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 401


@pytest.mark.parametrize("change", ["expired", "forged", "audience", "type", "missing_exp"])
def test_invalid_access_tokens_are_rejected(client: TestClient, change: str) -> None:
    result = login(client, create_user(client))
    claims = jwt.decode(result.json()["access_token"], options={"verify_signature": False})
    secret = SECRET
    if change == "expired":
        claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    if change == "forged":
        secret = "wrong-signing-key-at-least-32-characters"
    if change == "audience":
        claims["aud"] = "another-app"
    if change == "type":
        claims["type"] = "refresh"
    if change == "missing_exp":
        del claims["exp"]
    token = jwt.encode(claims, secret, algorithm="HS256")
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )


def test_disabled_account_and_role_changes_take_effect_immediately(client: TestClient) -> None:
    user = create_user(client, Role.MERCHANT)
    result = login(client, user)
    with Session(client.app.state.engine) as db, db.begin():
        db.execute(update(User).where(User.id == user.id).values(role="USER"))
    assert client.get("/api/v1/workspaces/merchant", headers=bearer(result)).status_code == 403
    with Session(client.app.state.engine) as db, db.begin():
        db.execute(update(User).where(User.id == user.id).values(is_active=False))
    assert client.get("/api/v1/auth/me", headers=bearer(result)).status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert login(client, user).status_code == 401


def test_expired_refresh_session_rejected(client: TestClient) -> None:
    login(client, create_user(client))
    with Session(client.app.state.engine) as db, db.begin():
        db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_csrf_header_and_origin_are_required(client: TestClient) -> None:
    assert client.post("/api/v1/auth/refresh", headers={"X-CSRF-Protection": ""}).status_code == 403
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_shared_database_login_rate_limit(client: TestClient) -> None:
    client.app.state.settings.login_account_rate_limit = 2
    user = create_user(client)
    assert login(client, user, password="bad").status_code == 401
    assert login(client, user, password="bad").status_code == 401
    response = login(client, user)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"


def test_concurrent_refresh_has_single_winner_and_replay_revocation(client: TestClient) -> None:
    user = create_user(client)
    result = login(client, user)
    raw = client.cookies.get("nearperk_refresh")

    def attempt() -> int:
        with TestClient(
            client.app, headers={**HEADERS, "Cookie": f"nearperk_refresh={raw}"}
        ) as other:
            return other.post("/api/v1/auth/refresh").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == [200, 401]
    assert client.get("/api/v1/auth/me", headers=bearer(result)).status_code == 401


def test_secure_cookie_enabled_in_production(client: TestClient) -> None:
    client.app.state.settings.cookie_secure = True
    response = login(client, create_user(client))
    assert "Secure" in response.headers["set-cookie"]


def test_production_rejects_development_auth_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", cookie_secure=False)
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret_key="too-short", cookie_secure=True)


def test_direct_client_cannot_spoof_rate_limit_identity(client: TestClient) -> None:
    client.app.state.settings.login_ip_rate_limit = 1
    user = create_user(client)
    payload = {"email": user.email, "password": PASSWORD, "workspace": user.role}
    assert (
        client.post(
            "/api/v1/auth/login", json=payload, headers={"X-Real-IP": "198.51.100.1"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/login", json=payload, headers={"X-Real-IP": "198.51.100.2"}
        ).status_code
        == 429
    )


def test_trusted_proxy_preserves_individual_client_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.state.settings.login_ip_rate_limit = 1
    client.app.state.settings.trusted_proxy_host = "frontend"
    monkeypatch.setattr(
        "app.auth.router.getaddrinfo",
        lambda *args: [(None, None, None, None, ("testclient", 0))],
    )
    user = create_user(client)
    payload = {"email": user.email, "password": PASSWORD, "workspace": user.role}
    for ip in ("198.51.100.1", "198.51.100.2"):
        assert (
            client.post("/api/v1/auth/login", json=payload, headers={"X-Real-IP": ip}).status_code
            == 200
        )
