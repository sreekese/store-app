from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_redemptions import confirm, preview, setup_coupon, staff

from app.auth.models import Role
from app.coupons.models import CouponClaim
from app.profiles.models import StaffAssignment

pytestmark = pytest.mark.integration


def get(client, headers, scope="merchant", days=7):
    return client.get(f"/api/v1/dashboards/{scope}?days={days}", headers=headers)


@pytest.mark.parametrize(
    "role,scope",
    [
        (Role.USER, "merchant"),
        (Role.USER, "platform"),
        (Role.USER, "staff"),
        (Role.MERCHANT, "platform"),
        (Role.MERCHANT_STAFF, "merchant"),
        (Role.ADMIN, "merchant"),
        (Role.SUPER_ADMIN, "staff"),
    ],
)
def test_dashboard_role_denials(client, role, scope):
    assert get(client, bearer(login(client, create_user(client, role))), scope).status_code == 403


@pytest.mark.parametrize(
    "role,scope",
    [
        (Role.MERCHANT, "merchant"),
        (Role.MERCHANT_STAFF, "staff"),
        (Role.ADMIN, "platform"),
        (Role.SUPER_ADMIN, "platform"),
    ],
)
def test_empty_dashboard_and_period_validation(client, role, scope):
    headers = bearer(login(client, create_user(client, role)))
    r = get(client, headers, scope)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert len(data["daily"]) == 7
    assert data["totals"]["redemptions"] == 0
    assert data["totals"]["recorded_purchase_amount"] == "0.00"
    assert data["top_offers"] == []
    if role != Role.MERCHANT_STAFF:
        assert data["totals"]["redemption_rate"] is None
    else:
        assert "claims" not in data["totals"]
        assert all("claims" not in d for d in data["daily"])
    for days in [0, 8, 91, "bad"]:
        assert get(client, headers, scope, days).status_code == 422
    assert len(get(client, headers, scope, 90).json()["daily"]) == 90


def test_real_transactions_scoped_totals_and_staff_revocation(client):
    owner, _, merchant, store, _, _, data = setup_coupon(client)
    user, staff_headers = staff(client, merchant, store)
    assert (
        confirm(
            client, staff_headers, data, preview(client, staff_headers, data).json()
        ).status_code
        == 200
    )
    result = get(client, owner).json()
    totals = result["totals"]
    assert {
        k: totals[k]
        for k in ["stores", "offers", "campaigns", "claims", "redemptions", "active_coupons"]
    } == {
        "stores": 1,
        "offers": 1,
        "campaigns": 1,
        "claims": 1,
        "redemptions": 1,
        "active_coupons": 0,
    }
    assert totals["redemption_rate"] == "100.00"
    assert totals["recorded_purchase_amount"] == "250.00"
    assert totals["coupon_benefit_amount"] == "50.00"
    assert sum(d["claims"] for d in result["daily"]) == 1
    assert sum(d["redemptions"] for d in result["daily"]) == 1
    assert result["top_offers"][0]["claims"] == 1
    assert data["claim_token"] not in str(result)
    outsider = bearer(login(client, create_user(client, Role.MERCHANT)))
    assert get(client, outsider).json()["totals"]["redemptions"] == 0
    other_staff, other_headers = staff(client, merchant, store)
    assert get(client, other_headers, "staff").json()["totals"]["redemptions"] == 0
    assert get(client, staff_headers, "staff").json()["totals"]["redemptions"] == 1
    with Session(client.app.state.engine) as db:
        db.delete(db.get(StaffAssignment, (user.id, UUID(store["id"]))))
        db.commit()
    assert get(client, staff_headers, "staff").json()["totals"]["redemptions"] == 0
    for role in [Role.ADMIN, Role.SUPER_ADMIN]:
        admin = bearer(login(client, create_user(client, role)))
        platform = get(client, admin, "platform").json()
        assert platform["totals"]["redemptions"] == 1
        assert platform["totals"]["merchants"] == 1
        assert platform["totals"]["users"] >= 6


def test_expiry_without_worker_and_indian_midnight_buckets(client):
    owner, _, _, _, _, claimed, _ = setup_coupon(client)
    now = datetime(2026, 9, 28, 18, 35, tzinfo=UTC)  # Sep 29, 00:05 IST
    with Session(client.app.state.engine) as db:
        row = db.get(CouponClaim, UUID(claimed["id"]))
        row.claimed_at = now - timedelta(minutes=10)  # Sep 28, 23:55 IST
        row.expires_at = now - timedelta(minutes=1)
        db.commit()
    with patch("app.dashboards.router.datetime") as clock:
        clock.now.return_value = now
        clock.combine = datetime.combine
        clock.min = datetime.min
        result = get(client, owner).json()
    assert result["totals"]["claims"] == 1
    assert result["totals"]["active_coupons"] == 0
    assert result["daily"][-2] == {"date": "2026-09-28", "claims": 1, "redemptions": 0}
    assert result["daily"][-1]["claims"] == 0


def test_period_does_not_change_lifetime_totals_or_mutate_claims(client):
    owner, _, _, _, _, claimed, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        row = db.get(CouponClaim, UUID(claimed["id"]))
        row.claimed_at = datetime.now(UTC) - timedelta(days=40)
        row.expires_at = datetime.now(UTC) - timedelta(days=39)
        db.commit()
    short, long = get(client, owner, days=7).json(), get(client, owner, days=90).json()
    assert short["totals"] == long["totals"]
    assert sum(d["claims"] for d in short["daily"]) == 0
    assert sum(d["claims"] for d in long["daily"]) == 1
    assert short["top_offers"] == []
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "CLAIMED"


def test_anonymous_and_csrf_denied(client):
    assert get(client, {}).status_code == 401
    headers = bearer(login(client, create_user(client, Role.MERCHANT)))
    assert get(client, {**headers, "Origin": "https://other.example"}).status_code == 403


def test_top_offers_bounded_and_multiple_campaigns_do_not_duplicate_counts(client):
    from uuid import uuid4

    from app.coupons.models import Campaign
    from app.offers.models import Offer

    owner, _, _, _, campaign_data, claimed, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        original_claim = db.get(CouponClaim, UUID(claimed["id"]))
        original_campaign = db.get(Campaign, UUID(campaign_data["id"]))
        original_offer = db.get(Offer, original_campaign.offer_id)
        for n in range(6):
            offer = Offer(
                **{
                    c.name: getattr(original_offer, c.name)
                    for c in Offer.__table__.columns
                    if c.name not in {"id", "created_at", "updated_at"}
                }
            )
            offer.title = f"Ranked offer {n}"
            db.add(offer)
            db.flush()
            for _ in range(2):
                item = Campaign(
                    offer_id=offer.id,
                    total_quantity=100,
                    claimed_count=n + 1,
                    starts_at=original_campaign.starts_at,
                    expires_at=original_campaign.expires_at,
                )
                db.add(item)
                db.flush()
                for _ in range(n + 1):
                    db.add(
                        CouponClaim(
                            campaign_id=item.id,
                            user_id=original_claim.user_id,
                            idempotency_key=uuid4(),
                            claim_token=str(uuid4()),
                            status="CANCELLED",
                            claimed_at=original_claim.claimed_at,
                            expires_at=original_claim.expires_at,
                            snapshot=original_claim.snapshot,
                        )
                    )
        db.commit()
    data = get(client, owner).json()
    assert data["totals"]["claims"] == 43
    assert data["totals"]["campaigns"] == 13
    assert data["totals"]["offers"] == 7
    assert data["totals"]["active_coupons"] == 1
    assert [o["claims"] for o in data["top_offers"]] == [12, 10, 8, 6, 4]
    assert sum(d["claims"] for d in data["daily"]) == 43
