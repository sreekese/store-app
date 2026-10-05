from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_offers import edit, fixture_offer

from app.auth.models import Role
from app.coupons.models import AllowanceUsage, Campaign, CouponClaim
from app.coupons.service import expire_claim, period
from app.jobs.models import Job
from app.jobs.service import process_one
from app.offers.models import Category, Offer
from app.profiles.models import AuditEvent, Merchant, Store

pytestmark = pytest.mark.integration


def payload(offer, store, **changes):
    return {
        "offer_id": offer["id"],
        "store_ids": [store["id"]],
        "total_quantity": 10,
        "per_user_limit": 1,
        "starts_at": offer["starts_at"],
        "expires_at": offer["expires_at"],
        **changes,
    }


def campaign(client, owner, offer, store, activate=True, **changes):
    response = client.post(
        "/api/v1/merchant/campaigns", headers=owner, json=payload(offer, store, **changes)
    )
    assert response.status_code == 201, response.text
    item = response.json()
    if activate:
        response = action(client, owner, item, "ACTIVATE")
        assert response.status_code == 200, response.text
        item = response.json()
    return item


def action(client, owner, item, command):
    return client.post(
        f"/api/v1/merchant/campaigns/{item['id']}/actions",
        headers=owner,
        json={"action": command, "revision": item["revision"]},
    )


def shopper(client):
    user = create_user(client)
    return user, bearer(login(client, user))


def claim(client, headers, item, key=None):
    return client.post(
        f"/api/v1/shopper/campaigns/{item['id']}/claim",
        headers={**headers, "Idempotency-Key": str(key or uuid4())},
    )


def test_campaign_draft_activation_edit_pause_cancel_and_audit(client):
    owner, admin, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, activate=False)
    assert item["status"] == "DRAFT"
    assert client.get(f"/api/v1/offers/{offer['id']}/campaigns").json() == []
    active = action(client, owner, item, "ACTIVATE").json()
    assert len(client.get(f"/api/v1/offers/{offer['id']}/campaigns").json()) == 1
    assert action(client, owner, item, "PAUSE").status_code == 409
    paused = action(client, owner, active, "PAUSE").json()
    assert paused["status"] == "PAUSED"
    cancelled = action(client, owner, paused, "CANCEL").json()
    assert action(client, owner, cancelled, "ACTIVATE").status_code == 409
    assert client.get("/api/v1/admin/campaigns", headers=admin).json()[0]["status"] == "CANCELLED"
    with Session(client.app.state.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("CAMPAIGN_%"))
            )
            == 4
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"total_quantity": 0},
        {"per_user_limit": 0},
        {"validity_hours": 0},
        {"store_ids": []},
        {"status": "ACTIVE"},
        {"claimed_count": -1},
        {"expires_at": "2020-01-01T00:00:00Z"},
    ],
)
def test_campaign_invalid_inputs(client, changes):
    owner, _, _, store, _, offer = fixture_offer(client)
    response = client.post(
        "/api/v1/merchant/campaigns", headers=owner, json=payload(offer, store, **changes)
    )
    assert response.status_code == 422


def test_owner_scope_roles_and_explicit_branches(client):
    owner, admin, _, store, _, offer = fixture_offer(client)
    _, other = shopper(client)
    item = campaign(client, owner, offer, store)
    for headers in (admin, other):
        assert (
            client.post(
                "/api/v1/merchant/campaigns", headers=headers, json=payload(offer, store)
            ).status_code
            == 403
        )
    assert claim(client, owner, item).status_code == 403
    assert claim(client, admin, item).status_code == 403
    staff = bearer(login(client, create_user(client, Role.MERCHANT_STAFF)))
    assert claim(client, staff, item).status_code == 403
    assert (
        client.post(
            "/api/v1/merchant/campaigns",
            headers=owner,
            json=payload(offer, store, store_ids=[str(uuid4())]),
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/merchant/campaigns",
            headers=owner,
            json=payload(offer, store, store_ids=[store["id"], store["id"]]),
        ).status_code
        == 422
    )
    outsider = bearer(login(client, create_user(client, Role.MERCHANT)))
    assert client.get("/api/v1/merchant/campaigns", headers=outsider).status_code == 404


def test_claim_snapshot_receipt_stock_allowance_and_outbox(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, validity_hours=3)
    user, headers = shopper(client)
    result = claim(client, headers, item)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "CLAIMED"
    assert "claim_token" not in data and "user_id" not in data
    assert datetime.fromisoformat(data["expires_at"]) - datetime.fromisoformat(
        data["claimed_at"]
    ) == timedelta(hours=3)
    allowance = client.get("/api/v1/shopper/allowance", headers=headers).json()
    assert allowance["remaining"] == 0 and allowance["timezone"] == "Asia/Kolkata"
    with Session(client.app.state.engine) as db:
        saved = db.get(CouponClaim, UUID(data["id"]))
        assert saved.snapshot["offer"]["discount_value"] == "20.00"
        assert saved.snapshot["branches"][0]["id"] == store["id"]
        assert saved.snapshot["branches"][0]["timezone"] == "Asia/Kolkata"
        assert len(saved.claim_token) >= 40
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 1
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.kind == "coupon.claimed"))
            == 1
        )
    from app.jobs.worker import handlers as worker_handlers

    for _ in range(10):
        if not process_one(client.app.state.engine, worker_handlers()):
            break
    else:
        raise AssertionError("Unexpected unbounded pending work")
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "COUPON_CLAIM_PROCESSED"))
    assert len(client.get("/api/v1/shopper/claims", headers=headers).json()) == 1
    _, other = shopper(client)
    assert client.get("/api/v1/shopper/claims", headers=other).json() == []


def test_same_key_returns_original_across_pause_expiry_and_conflicting_campaign(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    second = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    key = uuid4()
    first = claim(client, headers, item, key)
    assert first.status_code == 200
    with Session(client.app.state.engine) as db:
        db.get(Campaign, UUID(item["id"])).status = "CANCELLED"
        db.commit()
    assert claim(client, headers, item, key).json() == first.json()
    assert claim(client, headers, second, key).status_code == 409
    assert claim(client, headers, second).status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.get(Campaign, UUID(second["id"])).claimed_count == 0
        assert db.scalar(select(func.sum(AllowanceUsage.used))) == 1


def test_concurrent_same_request_is_idempotent(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    key = uuid4()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: claim(client, headers, item, key), range(6)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["id"] for r in results}) == 1
    with Session(client.app.state.engine) as db:
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 1


def test_concurrent_last_coupon_cannot_oversell(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, total_quantity=1)
    shoppers = [shopper(client)[1] for _ in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda headers: claim(client, headers, item), shoppers))
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]
    assert client.get(f"/api/v1/offers/{offer['id']}/campaigns").json() == []
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.sum(AllowanceUsage.used))) == 1
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 1


def test_concurrent_different_campaigns_share_allowance(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    items = [campaign(client, owner, offer, store) for _ in range(3)]
    _, headers = shopper(client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda item: claim(client, headers, item), items))
    assert sorted(r.status_code for r in results) == [200, 409, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.sum(Campaign.claimed_count))) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "PAUSED",
        "EXPIRED",
        "FUTURE",
        "OFFER_PAUSED",
        "CATEGORY_INACTIVE",
        "STORE_INACTIVE",
        "MERCHANT_SUSPENDED",
    ],
)
def test_unavailable_claims_consume_nothing(client, condition):
    owner, _, merchant, store, cat, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    with Session(client.app.state.engine) as db:
        c = db.get(Campaign, UUID(item["id"]))
        if condition == "PAUSED":
            c.status = "PAUSED"
        if condition == "EXPIRED":
            c.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if condition == "FUTURE":
            c.starts_at = datetime.now(UTC) + timedelta(hours=1)
        if condition == "OFFER_PAUSED":
            db.get(Offer, UUID(offer["id"])).status = "PAUSED"
        if condition == "CATEGORY_INACTIVE":
            db.get(Category, UUID(cat["id"])).is_active = False
        if condition == "STORE_INACTIVE":
            db.get(Store, UUID(store["id"])).status = "INACTIVE"
        if condition == "MERCHANT_SUSPENDED":
            db.get(Merchant, UUID(merchant["id"])).status = "SUSPENDED"
        db.commit()
    assert claim(client, headers, item).status_code == 409
    assert client.get("/api/v1/shopper/allowance", headers=headers).json()["remaining"] == 1
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(CouponClaim)) == 0
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 0


def test_existing_customer_requires_recorded_redemption(client):
    owner, _, _, store, _, offer = fixture_offer(client, customer_type="EXISTING_CUSTOMERS")
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    assert claim(client, headers, item).status_code == 409
    assert client.get("/api/v1/shopper/allowance", headers=headers).json()["remaining"] == 1


def test_period_midnight_boundary_and_lifetime_limit(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    now = datetime.now(UTC)
    start, end = period(now)
    assert period(end - timedelta(microseconds=1))[0] == start
    assert period(end)[0] == end
    assert claim(client, headers, item).status_code == 200
    with patch("app.coupons.service.datetime") as clock:
        clock.now.return_value = end + timedelta(seconds=1)
        assert claim(client, headers, item).status_code == 409  # per-user limit survives reset


def test_pausing_cancelling_editing_preserves_claim_and_no_refunds(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    response = claim(client, headers, item)
    saved_id = UUID(response.json()["id"])
    current = client.get("/api/v1/merchant/campaigns", headers=owner).json()[0]
    paused = action(client, owner, current, "PAUSE").json()
    assert action(client, owner, paused, "CANCEL").status_code == 200
    assert (
        edit(
            client, owner, offer, title="Changed offer", terms_conditions="Changed terms"
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        saved = db.get(CouponClaim, saved_id)
        assert saved.status == "CLAIMED" and saved.snapshot["offer"]["title"] == offer["title"]
        saved.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        saved.claimed_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
        expire_claim(db, {"claim_id": str(saved_id)})
        db.commit()
        assert saved.status == "EXPIRED"
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 1
    assert client.get("/api/v1/shopper/allowance", headers=headers).json()["remaining"] == 0


def test_edit_locks_terms_after_claim_but_allows_stock_increase(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, total_quantity=1)
    _, headers = shopper(client)
    assert claim(client, headers, item).status_code == 200
    current = client.get("/api/v1/merchant/campaigns", headers=owner).json()[0]
    data = {**payload(offer, store), "revision": current["revision"]}
    assert (
        client.put(
            f"/api/v1/merchant/campaigns/{item['id']}",
            headers=owner,
            json={**data, "per_user_limit": 2},
        ).status_code
        == 409
    )
    increased = client.put(f"/api/v1/merchant/campaigns/{item['id']}", headers=owner, json=data)
    assert increased.status_code == 200, increased.text
    assert increased.json()["available_count"] == 9 and increased.json()["status"] == "ACTIVE"
    assert (
        client.put(f"/api/v1/merchant/campaigns/{item['id']}", headers=owner, json=data).status_code
        == 409
    )


def test_claim_requires_key_csrf_and_no_spoofed_identity(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    path = f"/api/v1/shopper/campaigns/{item['id']}/claim"
    assert client.post(path, headers=headers).status_code == 422
    assert client.post(path, headers={**headers, "Idempotency-Key": "bad"}).status_code == 422
    assert (
        client.post(
            path, headers={**headers, "Idempotency-Key": str(uuid4()), "X-CSRF-Protection": "0"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/shopper/claims?offset=-1", headers=headers).status_code == 422
    assert client.get("/api/v1/merchant/campaigns?offset=10001", headers=owner).status_code == 422


def test_claim_outbox_failure_rolls_back_inventory_and_allowance(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    with patch("app.coupons.service.enqueue", side_effect=RuntimeError("test outbox failure")):
        response = claim(client, headers, item)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "test outbox failure" not in response.text
    with Session(client.app.state.engine) as db:
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 0
        assert db.scalar(select(func.count()).select_from(CouponClaim)) == 0
        assert db.scalar(select(func.count()).select_from(AllowanceUsage)) == 0
    assert claim(client, headers, item).status_code == 200


def test_next_day_allows_second_claim_only_with_new_request_key(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, per_user_limit=2)
    _, headers = shopper(client)
    key = uuid4()
    first = claim(client, headers, item, key)
    reset = period(datetime.now(UTC))[1]
    with patch("app.coupons.service.datetime") as clock:
        clock.now.return_value = reset
        assert claim(client, headers, item, key).json()["id"] == first.json()["id"]
        second = claim(client, headers, item)
        assert second.status_code == 200, second.text
        assert second.json()["id"] != first.json()["id"]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(AllowanceUsage)) == 2
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 2


def test_exact_expiry_and_duration_cap(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store, validity_hours=100)
    _, headers = shopper(client)
    first = claim(client, headers, item)
    assert first.status_code == 200
    assert datetime.fromisoformat(first.json()["expires_at"]) == datetime.fromisoformat(
        item["expires_at"]
    )
    _, another = shopper(client)
    with patch("app.coupons.service.datetime") as clock:
        clock.now.return_value = datetime.fromisoformat(item["expires_at"])
        assert claim(client, another, item).status_code == 409
    assert client.get("/api/v1/shopper/allowance", headers=another).json()["remaining"] == 1


def test_customer_eligibility_uses_redemption_not_prior_claim(client):
    owner, _, _, store, _, offer = fixture_offer(client, customer_type="NEW_CUSTOMERS")
    first_campaign = campaign(client, owner, offer, store)
    second_campaign = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    first = claim(client, headers, first_campaign)
    assert first.status_code == 200
    with Session(client.app.state.engine) as db:
        saved = db.get(CouponClaim, UUID(first.json()["id"]))
        saved.status = "REDEEMED"
        saved.redeemed_at = datetime.now(UTC)
        db.commit()
    with patch("app.coupons.service.datetime") as clock:
        clock.now.return_value = period(datetime.now(UTC))[1]
        denied = claim(client, headers, second_campaign)
        assert denied.status_code == 409 and "eligibility" in denied.text
        with Session(client.app.state.engine) as db:
            db.get(Offer, UUID(offer["id"])).customer_type = "EXISTING_CUSTOMERS"
            db.commit()
        allowed = claim(client, headers, second_campaign)
        assert allowed.status_code == 200, allowed.text
        with Session(client.app.state.engine) as db:
            assert (
                db.get(CouponClaim, UUID(allowed.json()["id"])).snapshot["eligibility"]
                == "EXISTING_CUSTOMER"
            )


def test_unapproved_offer_cannot_activate_campaign(client):
    owner, _, _, store, _, offer = fixture_offer(client, approved=False)
    item = campaign(client, owner, offer, store, activate=False)
    assert action(client, owner, item, "ACTIVATE").status_code == 409
    assert client.get("/api/v1/merchant/campaigns", headers=owner).json()[0]["status"] == "DRAFT"


def test_claimed_branch_snapshot_survives_store_edits(client):
    owner, _, _, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    _, headers = shopper(client)
    claimed = claim(client, headers, item).json()
    with Session(client.app.state.engine) as db:
        before = db.get(CouponClaim, UUID(claimed["id"])).snapshot["branches"]
        db.get(Store, UUID(store["id"])).name = "Renamed branch"
        db.get(Store, UUID(store["id"])).timezone = "UTC"
        db.commit()
        assert db.get(CouponClaim, UUID(claimed["id"])).snapshot["branches"] == before


def test_different_merchants_cannot_race_the_shared_daily_allowance(client):
    from test_locations import located
    from test_offers import action as submit_offer
    from test_offers import fields, review

    owner, admin, _, store, cat, offer = fixture_offer(client)
    first = campaign(client, owner, offer, store)
    other_owner, _, other_store = located(client)
    other_offer = client.post(
        "/api/v1/merchant/offers", headers=other_owner, json=fields(cat["id"])
    ).json()
    other_offer = review(
        client, admin, submit_offer(client, other_owner, other_offer, "SUBMIT").json()
    ).json()
    second = campaign(client, other_owner, other_offer, other_store)
    _, headers = shopper(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda c: claim(client, headers, c), [first, second]))
    assert sorted(r.status_code for r in results) == [200, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.sum(Campaign.claimed_count))) == 1
        assert db.scalar(select(func.sum(AllowanceUsage.used))) == 1
    assert (
        client.post(
            "/api/v1/merchant/campaigns", headers=owner, json=payload(offer, other_store)
        ).status_code
        == 403
    )
    assert action(client, other_owner, first, "PAUSE").status_code == 404
