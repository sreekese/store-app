import csv
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_billing import deliver, event, order, setup
from test_redemptions import confirm, preview, setup_coupon

from app.analytics.models import AnalyticsEvent
from app.auth.models import Role
from app.billing.models import Payment, Refund
from app.coupons.models import Campaign, CouponClaim
from app.profiles.models import Merchant
from app.redemptions.models import Redemption

pytestmark = pytest.mark.integration
BASE = "/api/v1/analytics"


def dates(**changes):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    return {
        "start_date": (today - timedelta(days=29)).isoformat(),
        "end_date": today.isoformat(),
        **changes,
    }


def get(client, headers, **params):
    return client.get(BASE + "/report", headers=headers, params=dates(**params))


@pytest.mark.parametrize("role", [Role.MERCHANT, Role.ADMIN, Role.SUPER_ADMIN])
def test_empty_report_and_csv(client, role):
    headers = bearer(login(client, create_user(client, role)))
    r = get(client, headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["claims"] == 0 and body["summary"]["cohort_rate"] is None
    assert len(body["daily"]) == 30
    assert ("revenue" in body) == (role == Role.SUPER_ADMIN)
    exported = client.get(BASE + "/export", headers=headers, params=dates())
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.headers["cache-control"] == "no-store"
    assert len(list(csv.DictReader(io.StringIO(exported.text)))) == 30


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT_STAFF])
def test_report_and_export_role_denials(client, role):
    headers = bearer(login(client, create_user(client, role)))
    assert get(client, headers).status_code == 403
    assert client.get(BASE + "/export", headers=headers, params=dates()).status_code == 403


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2020-01-01"},
        {"end_date": "2999-01-01"},
        {"start_date": "0001-01-01", "end_date": "0001-01-02"},
        {"start_date": "bad"},
        {"start_date": "2026-01-03", "end_date": "2026-01-01"},
        {"campaign_offset": -1},
    ],
)
def test_invalid_dates_and_pagination(client, params):
    headers = bearer(login(client, create_user(client, Role.ADMIN)))
    assert get(client, headers, **params).status_code == 422


def test_confirmed_transactions_cohorts_and_cross_merchant_privacy(client):
    owner, shopper, business, _, _, claimed, data = setup_coupon(client)
    assert confirm(client, owner, data, preview(client, owner, data).json()).status_code == 200
    r = get(client, owner)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["summary"]["claims"] == 1
    assert result["summary"]["redemptions"] == 1
    assert result["summary"]["cohort_rate"] == "100.00"
    assert result["summary"]["recorded_purchase_amount"] == "250.00"
    assert result["summary"]["engaged_shoppers"] == 1
    assert result["campaigns"]["items"][0]["cohort_rate"] == "100.00"
    assert data["claim_token"] not in r.text and "user_id" not in r.text
    outsider = bearer(login(client, create_user(client, Role.MERCHANT)))
    assert get(client, outsider).json()["summary"]["claims"] == 0
    assert get(client, outsider, merchant_id=business["id"]).status_code == 404
    assert get(client, owner, merchant_id=str(uuid4())).status_code == 404
    # Older claims redeemed in this period count as activity, not current-claim conversion.
    with Session(client.app.state.engine) as db:
        claim = db.get(CouponClaim, UUID(claimed["id"]))
        claim.claimed_at = datetime.now(UTC) - timedelta(days=40)
        db.commit()
    result = get(client, owner).json()
    assert result["summary"]["claims"] == 0 and result["summary"]["redemptions"] == 1
    assert result["summary"]["cohort_rate"] is None
    assert result["retention"]["retained_merchants"] == 1
    assert result["retention"]["rate"] == "100.00"


def test_views_deduplicate_and_reject_forged_success_or_private_targets(client):
    owner, shopper, _, store, _, claimed, _ = setup_coupon(client)
    payload = {"kind": "STORE_VIEWED", "target_id": store["id"]}
    for _ in range(2):
        assert client.post(BASE + "/events", headers=shopper, json=payload).status_code == 204
    assert client.post(BASE + "/events", headers=owner, json=payload).status_code == 403
    assert (
        client.post(
            BASE + "/events", headers=shopper, json={**payload, "kind": "PAYMENT_COMPLETED"}
        ).status_code
        == 422
    )
    other = bearer(login(client, create_user(client)))
    assert (
        client.post(
            BASE + "/events",
            headers=other,
            json={"kind": "COUPON_VIEWED", "target_id": claimed["id"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            BASE + "/events", headers=shopper, json={**payload, "target_id": str(uuid4())}
        ).status_code
        == 404
    )
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
    r = get(client, owner).json()
    assert {e["kind"]: e["count"] for e in r["events"]}["STORE_VIEWED"] == 1
    assert r["summary"]["engaged_shoppers"] == 1


def test_timezone_boundaries_and_no_future_cohort_redemptions(client):
    owner, _, _, _, _, claimed, data = setup_coupon(client)
    assert confirm(client, owner, data, preview(client, owner, data).json()).status_code == 200
    now = datetime(2026, 9, 29, 18, 35, tzinfo=UTC)
    with Session(client.app.state.engine) as db:
        c = db.get(CouponClaim, UUID(claimed["id"]))
        c.claimed_at = datetime(2026, 9, 28, 18, 29, tzinfo=UTC)
        c.expires_at = now + timedelta(days=1)
        redemption = db.scalar(select(Redemption).where(Redemption.claim_id == c.id))
        redemption.redeemed_at = datetime(2026, 9, 28, 18, 31, tzinfo=UTC)
        db.commit()
    with patch("app.analytics.router.datetime") as clock:
        clock.now.return_value = now
        first = get(client, owner, start_date="2026-09-28", end_date="2026-09-28").json()
        second = get(client, owner, start_date="2026-09-29", end_date="2026-09-29").json()
    assert first["summary"]["claims"] == 1 and first["summary"]["cohort_redeemed"] == 0
    assert second["summary"]["claims"] == 0 and second["summary"]["redemptions"] == 1
    assert first["daily"][0]["date"] == "2026-09-28"


def test_csv_formula_neutralization_and_billing_authorization(client):
    owner, _, business, _, _, _, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        db.get(Merchant, UUID(business["id"])).business_name = '  =HYPERLINK("bad")'
        db.commit()
    r = client.get(BASE + "/export", headers=owner, params=dates(kind="merchants"))
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows[0]["business_name"].startswith("'  =")
    for headers in [owner, bearer(login(client, create_user(client, Role.ADMIN)))]:
        assert "revenue" not in get(client, headers).json()
        assert (
            client.get(BASE + "/export", headers=headers, params=dates(kind="revenue")).status_code
            == 403
        )


def test_sandbox_revenue_and_refunds_are_separate_period_movements(client):
    owner, admin, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    assert deliver(client, event(client, payment)).status_code == 200
    r = get(client, admin)
    assert r.status_code == 200, r.text
    revenue = r.json()["revenue"]
    assert revenue == [
        {
            "provider": "sandbox",
            "currency": "INR",
            "gross_minor": 12000,
            "refund_minor": 0,
            "net_minor": 12000,
            "payments": 1,
        }
    ]
    with Session(client.app.state.engine) as db:
        row = db.get(Payment, UUID(payment["id"]))
        row.paid_at = datetime.now(UTC) - timedelta(days=60)
        db.commit()
    assert get(client, admin).json()["revenue"] == []

    response = client.post(
        f"/api/v1/billing/payments/{payment['id']}/refund",
        headers=admin,
        json={"reason": "Test refund in later period"},
    )
    assert response.status_code == 200
    with Session(client.app.state.engine) as db:
        refund_id = db.scalar(select(Refund.provider_refund_id))
    assert (
        deliver(client, event(client, payment, kind="REFUNDED", refund_id=refund_id)).status_code
        == 200
    )
    assert get(client, admin).json()["revenue"] == [
        {
            "provider": "sandbox",
            "currency": "INR",
            "gross_minor": 0,
            "refund_minor": 12000,
            "net_minor": -12000,
            "payments": 0,
        }
    ]


def test_campaign_pagination_and_export_includes_all_pages(client):
    owner, _, _, _, item, _, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        original = db.get(Campaign, UUID(item["id"]))
        for _ in range(21):
            db.add(
                Campaign(
                    offer_id=original.offer_id,
                    total_quantity=10,
                    per_user_limit=1,
                    starts_at=original.starts_at,
                    expires_at=original.expires_at,
                    status="DRAFT",
                )
            )
        db.commit()
    first = get(client, owner).json()["campaigns"]
    second = get(client, owner, campaign_offset=20).json()["campaigns"]
    assert len(first["items"]) == 20 and first["next_offset"] == 20
    assert len(second["items"]) == 2 and second["next_offset"] is None
    assert not ({r["id"] for r in first["items"]} & {r["id"] for r in second["items"]})
    exported = client.get(
        BASE + "/export", headers=owner, params=dates(kind="campaigns", campaign_offset=20)
    )
    assert exported.status_code == 200
    assert len(list(csv.DictReader(io.StringIO(exported.text)))) == 22
