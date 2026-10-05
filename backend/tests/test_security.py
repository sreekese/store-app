import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import PASSWORD, bearer, create_user, login

from app.auth.audit import SecurityEvent
from app.core.config import Settings
from app.core.security import SecurityBoundary
from app.main import create_app


def config(**changes):
    return Settings(_env_file=None, **changes)


def test_security_headers_and_request_ids_on_success_error_and_not_found():
    with TestClient(create_app(config())) as client:
        for path in ["/health", "/missing", "/api/v1/workspaces/superadmin"]:
            r = client.get(path, headers={"X-Request-ID": "untrusted"})
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["x-content-type-options"] == "nosniff"
            assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
            assert r.headers["x-request-id"] != "untrusted"
            assert "strict-transport-security" not in r.headers
            if r.status_code >= 400:
                assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "origins",
    [
        ["*"],
        ["https://*.example.com"],
        ["https://example.com/path"],
        ["https://user:password@example.com"],
        ["null"],
        ["https://example.com/"],
    ],
)
def test_unsafe_cors_configuration_rejected(origins):
    with pytest.raises(ValidationError):
        config(cors_origins=origins)


def test_production_requires_public_origins_hosts_and_disables_docs():
    settings = config(
        app_env="production",
        jwt_secret_key="private-production-signing-key-for-test-123",
        cookie_secure=True,
        cors_origins=["https://nearperk.example"],
        allowed_hosts=["nearperk.example"],
    )
    with TestClient(create_app(settings), base_url="https://nearperk.example") as client:
        for path in ["/docs", "/redoc", "/openapi.json"]:
            assert client.get(path).status_code == 404
        r = client.get("/health")
        assert r.headers["strict-transport-security"] == "max-age=31536000"
        assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
    with pytest.raises(ValidationError):
        config(
            app_env="production",
            jwt_secret_key="private-production-signing-key-for-test-123",
            cookie_secure=True,
        )
    with pytest.raises(ValidationError):
        config(allowed_hosts=["*"])


@pytest.mark.parametrize(
    "headers,body,status",
    [
        ({"Content-Type": "application/json"}, b"x" * 1025, 413),
        ({"Content-Type": "multipart/form-data; boundary=test"}, b"file-content", 415),
        ({"Content-Type": "text/plain"}, b"password=secret", 415),
        ({"Content-Type": "application/json", "Content-Encoding": "gzip"}, b"compressed", 415),
        ({"Content-Type": "application/json", "Content-Length": "1"}, b"{}", 400),
        ({"Content-Type": "application/json", "Content-Length": "-1"}, b"{}", 400),
    ],
)
def test_request_limits_reject_before_parsing(headers, body, status):
    with TestClient(create_app(config(max_request_bytes=1024))) as client:
        r = client.post("/api/v1/auth/login", content=body, headers=headers)
        assert r.status_code == status, r.text
        assert r.headers["x-frame-options"] == "DENY"
        assert "secret" not in r.text and "file-content" not in r.text
        assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_oversize_rejection_retains_only_allowed_cors_origin():
    with TestClient(create_app(config(max_request_bytes=1024))) as client:
        for origin in ["http://localhost:5173", "https://attacker.example"]:
            r = client.post("/api/v1/auth/login", content=b"x" * 1025, headers={"Origin": origin})
            assert ("access-control-allow-origin" in r.headers) == (
                origin == "http://localhost:5173"
            )
            assert r.status_code == 413
        assert client.get("/health?" + "x" * 4097).status_code == 414
        assert client.get("/health", headers={"Cookie": "x" * 17000}).status_code == 431


def test_chunked_and_slow_bodies_are_bounded():
    async def scenario(slow):
        called = False

        async def app(scope, receive, send):
            nonlocal called
            called = True

        count = 0

        async def receive():
            nonlocal count
            count += 1
            if slow:
                await asyncio.sleep(0.1)
            return {"type": "http.request", "body": b"x" * 600, "more_body": True}

        messages = []

        async def send(message):
            messages.append(message)

        boundary = SecurityBoundary(
            app, config(max_request_bytes=1024, request_body_timeout_seconds=0.02)
        )
        await boundary(
            {"type": "http", "path": "/api/v1/auth/login", "headers": [], "query_string": b""},
            receive,
            send,
        )
        assert not called
        assert messages[0]["status"] == (408 if slow else 413)
        if not slow:
            assert count == 2

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


def test_unexpected_errors_do_not_leak_details(caplog):
    app = create_app(config())

    @app.get("/explode")
    def explode():
        raise RuntimeError("private-password-and-database-details")

    with TestClient(app) as client:
        r = client.get("/explode")
    assert r.status_code == 500
    assert "private-password" not in r.text and "private-password" not in caplog.text
    assert r.headers["x-frame-options"] == "DENY"
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.integration
def test_security_audit_records_rotation_replay_and_logout_without_secrets(client):
    user = create_user(client)
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Wrong-secret-password", "workspace": "USER"},
    )
    assert bad.status_code == 401
    good = login(client, user)
    original = good.cookies.get("nearperk_refresh")
    assert client.post("/api/v1/auth/refresh").status_code == 200
    client.cookies.set("nearperk_refresh", original, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.clear()
    good = login(client, user)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(good)).status_code == 401
    with Session(client.app.state.engine) as db:
        rows = list(db.scalars(select(SecurityEvent)))
        assert {r.kind for r in rows} >= {
            "LOGIN_FAILED",
            "LOGIN_SUCCEEDED",
            "REFRESH_ROTATED",
            "REFRESH_REPLAY_REVOKED",
            "LOGOUT_REVOKED",
        }
        encoded = json.dumps(
            [{k: str(v) for k, v in r.__dict__.items() if not k.startswith("_")} for r in rows]
        )
        for secret in [PASSWORD, user.email, original, good.json()["access_token"]]:
            assert secret not in encoded


@pytest.mark.integration
def test_authenticated_mutations_have_per_account_limit(client):
    headers = bearer(login(client, create_user(client)))
    client.app.state.settings.mutation_rate_limit = 1
    payload = {"kind": "STORE_VIEWED", "target_id": str(uuid4())}
    assert client.post("/api/v1/analytics/events", headers=headers, json=payload).status_code == 404
    r = client.post("/api/v1/analytics/events", headers=headers, json=payload)
    assert r.status_code == 429 and r.headers["retry-after"] == "900"
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
