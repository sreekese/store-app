from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import make_engine
from app.main import create_app

SECRET = "scheduler-test-key-never-used-for-production"


def test_serverless_connections_do_not_keep_idle_pools():
    engine = make_engine(Settings().database_url, serverless=True)
    assert isinstance(engine.pool, NullPool)
    engine.dispose()


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic " + SECRET])
def test_scheduler_rejects_unauthorized_calls_without_processing(authorization):
    with TestClient(create_app(Settings(cron_secret=SECRET))) as client:
        with patch("app.jobs.router.schedule_daily") as schedule:
            response = client.post(
                "/api/internal/jobs",
                headers={"Authorization": authorization} if authorization else {},
            )
        assert response.status_code == 403
        schedule.assert_not_called()
        assert response.headers["cache-control"] == "no-store"


def test_scheduler_is_disabled_without_secret():
    with TestClient(create_app(Settings(cron_secret=""))) as client:
        assert client.get("/api/internal/jobs").status_code == 404


def test_scheduler_bounds_work_and_stops_on_empty_queue():
    with TestClient(create_app(Settings(cron_secret=SECRET))) as client:
        with (
            patch("app.jobs.router.schedule_daily", return_value=2),
            patch("app.jobs.router.process_one", return_value=True) as process,
        ):
            response = client.post(
                "/api/internal/jobs", headers={"Authorization": f"Bearer {SECRET}"}
            )
            assert response.json() == {"scheduled": 2, "processed": 20}
            assert process.call_count == 20
        with (
            patch("app.jobs.router.schedule_daily", return_value=0),
            patch("app.jobs.router.process_one", return_value=False) as process,
        ):
            response = client.get(
                "/api/internal/jobs", headers={"Authorization": f"Bearer {SECRET}"}
            )
            assert response.json() == {"scheduled": 0, "processed": 0}
            assert process.call_count == 1


def test_scheduler_observes_elapsed_time_limit():
    with TestClient(create_app(Settings(cron_secret=SECRET))) as client:
        with (
            patch("app.jobs.router.schedule_daily", return_value=0),
            patch("app.jobs.router.monotonic", side_effect=[0, 21]),
            patch("app.jobs.router.process_one") as process,
        ):
            response = client.post(
                "/api/internal/jobs", headers={"Authorization": f"Bearer {SECRET}"}
            )
            assert response.json() == {"scheduled": 0, "processed": 0}
            process.assert_not_called()


@pytest.mark.parametrize("vercel,expected", [(False, "testclient"), (True, "203.0.113.8")])
def test_platform_forwarded_ip_trust_requires_server_setting(vercel, expected):
    from starlette.requests import Request

    from app.auth.router import peer

    app = create_app(Settings(vercel=vercel))
    request = Request(
        {
            "type": "http",
            "app": app,
            "client": ("testclient", 1234),
            "headers": [(b"x-vercel-forwarded-for", b"203.0.113.8")],
        }
    )
    assert peer(request) == expected


@pytest.mark.integration
def test_authenticated_scheduler_processes_real_queue(client):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.jobs.models import Job
    from app.jobs.service import enqueue

    client.app.state.settings.cron_secret = Settings(cron_secret=SECRET).cron_secret
    with Session(client.app.state.engine) as db:
        job_id = enqueue(db, kind="system.noop", payload={}, key="serverless-test")
        db.commit()
    response = client.post("/api/internal/jobs", headers={"Authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(Job.status).where(Job.id == job_id)) == "completed"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_managed_database_urls_use_installed_psycopg_driver(scheme):
    settings = Settings(database_url=f"{scheme}://example:example@db.example/app?sslmode=require")
    assert settings.database_url == (
        "postgresql+psycopg://example:example@db.example/app?sslmode=require"
    )
