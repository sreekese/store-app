from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_coupons import campaign, claim, shopper
from test_offers import fixture_offer

from app.auth.models import Role
from app.coupons.models import CouponClaim
from app.daily.models import CouponPolicy, Recommendation
from app.daily.policy import Rules, active, window

pytestmark = pytest.mark.integration


def fixture(client):
    owner, admin, merchant, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, per_user_limit=10)
    user, headers = shopper(client)
    superadmin = bearer(login(client, create_user(client, Role.SUPER_ADMIN)))
    return owner, admin, store, item, user, headers, superadmin


def search(client, headers, store, **changes):
    return client.post(
        "/api/v1/daily/recommendations",
        headers=headers,
        json={
            "latitude": store["latitude"],
            "longitude": store["longitude"],
            "radius_km": 5,
            **changes,
        },
    )


def test_recommendation_is_durable_private_and_never_claims(client):
    owner, admin, store, item, user, headers, superadmin = fixture(client)
    a, b = search(client, headers, store), search(client, headers, store)
    assert a.status_code == 200, a.text
    assert a.json()["recommendation"] == b.json()["recommendation"]
    assert a.json()["recommendation"]["campaign_id"] == item["id"]
    assert a.json()["allowance"]["remaining"] == 1
    assert a.headers["cache-control"] == "no-store"
    assert "claim_token" not in a.text
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1
        assert db.scalar(select(func.count()).select_from(CouponClaim)) == 0
    assert search(client, headers, store, longitude=0, latitude=0).json()["recommendation"] is None
    assert client.get("/api/v1/shopper/allowance", headers=headers).json()["remaining"] == 1
    assert search(client, headers, store, radius_km=11).status_code == 422


def test_pick_override_none_removal_and_future_date_isolation(client):
    owner, admin, store, item, user, headers, superadmin = fixture(client)
    day = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    path = f"/api/v1/daily/stores/{store['id']}/picks/{day}"
    payload = {"campaign_id": item["id"], "revision": 0}
    assert client.put(path, headers=owner, json=payload).status_code == 200
    assert len(search(client, headers, store).json()["daily_picks"]) == 1
    assert (
        client.put(path, headers=superadmin, json={"campaign_id": None, "revision": 0}).status_code
        == 200
    )
    assert search(client, headers, store).json()["daily_picks"] == []
    assert client.delete(path + "?revision=1", headers=superadmin).status_code == 200
    assert len(search(client, headers, store).json()["daily_picks"]) == 1
    tomorrow = day + timedelta(days=1)
    assert (
        client.put(
            f"/api/v1/daily/stores/{store['id']}/picks/{tomorrow}", headers=owner, json=payload
        ).status_code
        == 200
    )
    assert client.get(path, headers=owner).json()["MERCHANT"]["revision"] == 1
    assert client.put(path, headers=owner, json=payload).status_code == 409
    assert len(client.get(f"/api/v1/daily/stores/{store['id']}/history", headers=owner).json()) == 4
    assert client.put(path, headers=admin, json=payload).status_code == 403


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT, Role.MERCHANT_STAFF, Role.ADMIN])
def test_only_superadmin_can_manage_policy(client, role):
    headers = bearer(login(client, create_user(client, role)))
    assert client.get("/api/v1/daily/policy/history", headers=headers).status_code == 403
    assert client.delete("/api/v1/daily/policy/1", headers=headers).status_code == 403


def test_policy_preview_schedule_cancel_and_boundary_validation(client):
    _, _, _, _, _, headers, superadmin = fixture(client)
    with Session(client.app.state.engine) as db:
        boundary = window(active(db, datetime.now(UTC)), datetime.now(UTC))[1]
    payload = {
        **Rules(allowance=3, period="WEEKLY").model_dump(),
        "current_version": 1,
        "effective_at": boundary.isoformat(),
    }
    preview = client.post("/api/v1/daily/policy/preview", headers=superadmin, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_users"] == 1
    saved = client.post("/api/v1/daily/policy/schedule", headers=superadmin, json=payload)
    assert saved.status_code == 200, saved.text
    assert client.get("/api/v1/shopper/allowance", headers=headers).json()["limit"] == 1
    assert (
        client.post("/api/v1/daily/policy/schedule", headers=superadmin, json=payload).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/daily/policy/{saved.json()['version']}", headers=superadmin
        ).status_code
        == 200
    )
    assert len(client.get("/api/v1/daily/policy/history", headers=superadmin).json()["audit"]) == 2
    payload["effective_at"] = (boundary + timedelta(minutes=1)).isoformat()
    assert (
        client.post("/api/v1/daily/policy/preview", headers=superadmin, json=payload).status_code
        == 422
    )
    payload["timezone"] = "Invalid/Zone"
    assert (
        client.post("/api/v1/daily/policy/preview", headers=superadmin, json=payload).status_code
        == 422
    )
    assert client.delete("/api/v1/daily/policy/1", headers=superadmin).status_code == 409


def test_activation_clips_new_timezone_period_without_double_allowance(client):
    _, _, store, item, user, headers, superadmin = fixture(client)
    assert claim(client, headers, item).status_code == 200
    now = datetime.now(UTC)
    with Session(client.app.state.engine) as db:
        boundary = window(active(db, now), now)[1]
        policy = CouponPolicy(
            effective_at=boundary,
            rules=Rules(allowance=2, period="WEEKLY", timezone="America/New_York").model_dump(),
        )
        db.add(policy)
        db.commit()
        version = policy.version
        start, end = window(policy, boundary)
        assert start == boundary and end > boundary
    future = boundary + timedelta(seconds=1)
    with patch("app.coupons.router.datetime") as clock:
        clock.now.return_value = future
        data = client.get("/api/v1/shopper/allowance", headers=headers).json()
    assert data["used"] == 0 and data["remaining"] == 2 and data["policy_version"] == version
    with patch("app.coupons.service.datetime") as clock:
        clock.now.return_value = future
        responses = list(
            ThreadPoolExecutor(max_workers=3).map(lambda _: claim(client, headers, item), range(3))
        )
    assert sorted(r.status_code for r in responses) == [200, 200, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(CouponClaim)) == 3


def test_candidates_and_recommendations_recheck_stock_and_eligibility(client):
    from app.coupons.models import Campaign
    from app.offers.models import Offer

    owner, _, store, item, _, headers, _ = fixture(client)
    assert search(client, headers, store).json()["recommendation"] is not None
    with Session(client.app.state.engine) as db:
        row = db.get(Campaign, UUID(item["id"]))
        row.claimed_count = row.total_quantity
        db.commit()
    assert search(client, headers, store).json()["recommendation"] is None
    with Session(client.app.state.engine) as db:
        row = db.get(Campaign, UUID(item["id"]))
        row.claimed_count = 0
        db.get(Offer, row.offer_id).customer_type = "EXISTING_CUSTOMERS"
        db.commit()
    assert search(client, headers, store).json()["recommendation"] is None


def test_foreign_store_staff_admin_and_anonymous_denied(client):
    _, _, store, item, _, headers, _ = fixture(client)
    date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    for role in [Role.MERCHANT, Role.MERCHANT_STAFF, Role.ADMIN]:
        actor = bearer(login(client, create_user(client, role)))
        path = f"/api/v1/daily/stores/{store['id']}/picks/{date}"
        assert client.get(path, headers=actor).status_code == 403
        assert (
            client.put(
                path, headers=actor, json={"campaign_id": item["id"], "revision": 0}
            ).status_code
            == 403
        )
        assert search(client, actor, store).status_code == 403
    assert search(client, {}, store).status_code == 401


def test_concurrent_recommendations_store_one_selection(client):
    _, _, store, _, _, headers, _ = fixture(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: search(client, headers, store), range(4)))
    assert all(r.status_code == 200 for r in responses)
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Recommendation)) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "PAUSED",
        "STORE_INACTIVE",
        "MERCHANT_SUSPENDED",
        "CATEGORY_INACTIVE",
        "PER_USER_LIMIT",
        "OFFER_HOLD",
    ],
)
def test_invalidated_recommendation_is_removed_on_next_read(client, condition):
    from app.coupons.models import Campaign
    from app.offers.models import Category, Offer
    from app.profiles.models import Merchant, Store

    owner, _, store, item, _, headers, _ = fixture(client)
    assert search(client, headers, store).json()["recommendation"]
    with Session(client.app.state.engine) as db:
        c = db.get(Campaign, UUID(item["id"]))
        offer = db.get(Offer, c.offer_id)
        if condition == "PAUSED":
            c.status = "PAUSED"
        if condition == "STORE_INACTIVE":
            db.get(Store, UUID(store["id"])).status = "INACTIVE"
        if condition == "MERCHANT_SUSPENDED":
            db.get(Merchant, offer.merchant_id).status = "SUSPENDED"
        if condition == "CATEGORY_INACTIVE":
            db.get(Category, offer.category_id).is_active = False
        if condition == "OFFER_HOLD":
            offer.admin_hold = True
        if condition == "PER_USER_LIMIT":
            c.per_user_limit = 1
        db.commit()
    if condition == "PER_USER_LIMIT":
        assert claim(client, headers, item).status_code == 200
    assert search(client, headers, store).json()["recommendation"] is None


def test_simultaneous_policy_schedules_have_one_winner(client):
    _, _, _, _, _, _, superadmin = fixture(client)
    with Session(client.app.state.engine) as db:
        boundary = window(active(db, datetime.now(UTC)), datetime.now(UTC))[1]
    payload = {
        **Rules(allowance=2).model_dump(),
        "current_version": 1,
        "effective_at": boundary.isoformat(),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: client.post(
                    "/api/v1/daily/policy/schedule", headers=superadmin, json=payload
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]


def test_weekly_window_handles_daylight_saving_calendar_boundary():
    policy = CouponPolicy(
        version=2,
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        rules=Rules(period="WEEKLY", timezone="America/New_York").model_dump(),
    )
    start, end = window(policy, datetime(2026, 3, 8, 12, tzinfo=UTC))
    assert start == datetime(2026, 3, 2, 5, tzinfo=UTC)
    assert end == datetime(2026, 3, 9, 4, tzinfo=UTC)
    assert (end - start).total_seconds() == 167 * 3600
