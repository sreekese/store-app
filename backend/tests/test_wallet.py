from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_coupons import campaign, claim, shopper
from test_offers import fixture_offer

from app.auth.models import Role, User
from app.coupons.models import Campaign, CouponClaim
from app.offers.models import Offer
from app.profiles.models import Merchant, Store

pytestmark = pytest.mark.integration


def saved(client):
    owner, admin, merchant, store, cat, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    user, headers = shopper(client)
    result = claim(client, headers, item)
    assert result.status_code == 200
    return headers, result.json(), owner, merchant, store, offer


def test_wallet_owner_only_and_no_codes_in_lists(client):
    headers, coupon, owner, _, _, _ = saved(client)
    page = client.get("/api/v1/shopper/wallet", headers=headers)
    assert page.status_code == 200 and len(page.json()["claims"]) == 1
    assert "claim_token" not in page.text and "snapshot" not in page.text
    assert page.headers["cache-control"] == "no-store"
    detail = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["claim_token"]) >= 40
    assert detail.headers["cache-control"] == "no-store"
    assert "user_id" not in detail.json() and "idempotency_key" not in detail.json()
    _, other = shopper(client)
    assert client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=other).status_code == 404
    assert client.get(f"/api/v1/shopper/wallet/{uuid4()}", headers=other).status_code == 404
    assert client.get("/api/v1/shopper/wallet", headers=owner).status_code == 403
    assert client.get(f"/api/v1/shopper/wallet/{coupon['id']}").status_code == 401


@pytest.mark.parametrize("role", [Role.ADMIN, Role.SUPER_ADMIN, Role.MERCHANT_STAFF])
def test_management_cannot_access_shopper_wallet(client, role):
    _, coupon, _, _, _, _ = saved(client)
    headers = bearer(login(client, create_user(client, role)))
    assert client.get("/api/v1/shopper/wallet", headers=headers).status_code == 403
    assert client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).status_code == 403


@pytest.mark.parametrize("state", ["EXPIRED", "REDEEMED", "CANCELLED"])
def test_terminal_states_never_disclose_codes(client, state):
    headers, coupon, _, _, _, _ = saved(client)
    with Session(client.app.state.engine) as db:
        saved_claim = db.get(CouponClaim, UUID(coupon["id"]))
        saved_claim.status = state
        if state == "REDEEMED":
            saved_claim.redeemed_at = datetime.now(UTC)
        db.commit()
    result = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).json()
    assert result["status"] == state and result["claim_token"] is None
    assert (
        len(client.get(f"/api/v1/shopper/wallet?status={state}", headers=headers).json()["claims"])
        == 1
    )
    assert client.get("/api/v1/shopper/wallet", headers=headers).json()["claims"] == []
    assert (result["redeemed_at"] is not None) == (state == "REDEEMED")


def test_expired_claim_without_worker_moves_to_expired_tab(client):
    headers, coupon, _, _, _, _ = saved(client)
    with Session(client.app.state.engine) as db:
        c = db.get(CouponClaim, UUID(coupon["id"]))
        c.claimed_at = datetime.now(UTC) - timedelta(hours=1)
        c.expires_at = datetime.now(UTC) - timedelta(microseconds=1)
        db.commit()
    result = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).json()
    assert result["status"] == "EXPIRED" and result["claim_token"] is None
    assert client.get("/api/v1/shopper/wallet", headers=headers).json()["claims"] == []
    assert (
        len(client.get("/api/v1/shopper/wallet?status=EXPIRED", headers=headers).json()["claims"])
        == 1
    )


@pytest.mark.parametrize("change", ["merchant", "owner", "branch"])
def test_temporarily_unavailable_keeps_terms_but_hides_codes(client, change):
    headers, coupon, _, merchant, store, _ = saved(client)
    with Session(client.app.state.engine) as db:
        m = db.get(Merchant, UUID(merchant["id"]))
        if change == "merchant":
            m.status = "SUSPENDED"
        if change == "owner":
            db.get(User, m.owner_id).is_active = False
        if change == "branch":
            db.get(Store, UUID(store["id"])).status = "INACTIVE"
        db.commit()
    data = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).json()
    assert data["status"] == "CLAIMED" and data["claim_token"] is None
    assert not data["branches"][0]["currently_available"]
    assert "temporarily unavailable" in data["availability_message"]
    assert data["offer"]["terms_conditions"]


def test_distribution_cancel_and_later_edits_do_not_replace_snapshot(client):
    headers, coupon, _, _, store, offer = saved(client)
    before = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).json()
    with Session(client.app.state.engine) as db:
        c = db.get(CouponClaim, UUID(coupon["id"]))
        db.get(Campaign, c.campaign_id).status = "CANCELLED"
        o = db.get(Offer, UUID(offer["id"]))
        o.status = "DRAFT"
        o.terms_conditions = "New terms"
        o.discount_value = 5
        db.get(Store, UUID(store["id"])).name = "Renamed store"
        db.commit()
    after = client.get(f"/api/v1/shopper/wallet/{coupon['id']}", headers=headers).json()
    assert after["offer"] == before["offer"]
    assert after["branches"] == before["branches"]
    assert after["claim_token"] == before["claim_token"]
    assert after["expires_at"] == before["expires_at"]


def test_stable_pagination_and_validation(client):
    headers, coupon, _, _, _, _ = saved(client)
    with Session(client.app.state.engine) as db:
        original = db.get(CouponClaim, UUID(coupon["id"]))
        for _ in range(14):
            db.add(
                CouponClaim(
                    campaign_id=original.campaign_id,
                    user_id=original.user_id,
                    idempotency_key=uuid4(),
                    claim_token=uuid4().hex,
                    claimed_at=original.claimed_at,
                    expires_at=original.expires_at,
                    snapshot=original.snapshot,
                )
            )
        db.commit()
    first = client.get("/api/v1/shopper/wallet", headers=headers).json()
    second = client.get("/api/v1/shopper/wallet?offset=12", headers=headers).json()
    assert len(first["claims"]) == 12 and first["next_offset"] == 12
    assert len(second["claims"]) == 3 and second["next_offset"] is None
    assert len({c["id"] for c in first["claims"] + second["claims"]}) == 15
    for query in ("status=UNKNOWN", "offset=-1", "limit=51", "offset=10001"):
        assert client.get("/api/v1/shopper/wallet?" + query, headers=headers).status_code == 422
    assert (
        client.get(
            "/api/v1/shopper/wallet", headers={**headers, "X-CSRF-Protection": "0"}
        ).status_code
        == 403
    )
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(Campaign.claimed_count)) == 1  # reads never mutate stock
