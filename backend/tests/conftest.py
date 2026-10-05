import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.advertisements.models import Advertisement
from app.auth.audit import SecurityEvent
from app.auth.models import AuthRateLimit, AuthSession, RefreshToken, User
from app.billing.models import BillingEvent, Payment, Plan, Refund
from app.core.config import Settings
from app.core.database import make_engine
from app.daily.models import CouponPolicy
from app.jobs.models import Job
from app.main import create_app
from app.offers.models import Category
from app.profiles.models import AuditEvent

SECRET = "test-only-signing-key-not-a-production-secret-123"
HEADERS = {"X-CSRF-Protection": "1", "Origin": "http://localhost:5173"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated migrated PostgreSQL database")
    engine = make_engine(url)
    assert engine.url.database and engine.url.database.endswith("_test")
    with engine.begin() as connection:
        connection.execute(delete(CouponPolicy).where(CouponPolicy.version != 1))
        for model in (
            SecurityEvent,
            BillingEvent,
            Refund,
            Payment,
            Plan,
            Advertisement,
            RefreshToken,
            AuthSession,
            User,
            AuthRateLimit,
            AuditEvent,
            Category,
            Job,
        ):
            connection.execute(delete(model))
    engine.dispose()
    app = create_app(
        Settings(
            database_url=url,
            jwt_secret_key=SECRET,
            login_account_rate_limit=100,
            login_ip_rate_limit=200,
            register_rate_limit=100,
            refresh_rate_limit=200,
        )
    )
    with TestClient(app, headers=HEADERS) as test_client:
        yield test_client
