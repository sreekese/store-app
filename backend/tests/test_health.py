from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_liveness_does_not_require_database() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_readiness_reports_database_failure_without_details() -> None:
    with patch("app.main.database_ready", return_value=False), TestClient(create_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "password" not in response.text.lower()


def test_readiness_success() -> None:
    with patch("app.main.database_ready", return_value=True), TestClient(create_app()) as client:
        assert client.get("/ready").json() == {"status": "ready"}


def test_cors_rejects_untrusted_origin() -> None:
    with TestClient(create_app(Settings(cors_origins=["http://localhost:5173"]))) as client:
        response = client.options(
            "/health",
            headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_accepts_configured_origin() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_and_versioned_metadata() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/status").json()["sprint"] == 16
        assert "/ready" in client.get("/openapi.json").json()["paths"]
