from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_coupons import campaign, claim, shopper
from test_offers import fields, fixture_offer

from app.auth.models import Role
from app.auth.service import AuthError
from app.coupons.models import Campaign, CouponClaim
from app.jobs.models import Job
from app.offers.schemas import OfferInput
from app.profiles.models import AuditEvent, Merchant, StaffAssignment, Store
from app.redemptions.models import Redemption
from app.redemptions.service import calculate

pytestmark = pytest.mark.integration


def setup_coupon(client):
    owner, admin, merchant, store, _, offer = fixture_offer(client)
    item = campaign(client, owner, offer, store)
    user, user_headers = shopper(client)
    claimed = claim(client, user_headers, item).json()
    with Session(client.app.state.engine) as db:
        code = db.get(CouponClaim, UUID(claimed["id"])).claim_token
    data = {"store_id": store["id"], "claim_token": code, "purchase_amount": "250.00"}
    return owner, user_headers, merchant, store, item, claimed, data


def preview(client, headers, data):
    return client.post("/api/v1/redemptions/validate", headers=headers, json=data)


def confirm(client, headers, data, validated, key=None, **changes):
    return client.post(
        "/api/v1/redemptions",
        headers={**headers, "Idempotency-Key": str(key or uuid4())},
        json={
            **data,
            "confirmation_token": validated["confirmation_token"],
            "terms_confirmed": True,
            **changes,
        },
    )


def staff(client, merchant, store):
    user = create_user(client, Role.MERCHANT_STAFF)
    with Session(client.app.state.engine) as db:
        db.add(
            StaffAssignment(
                staff_id=user.id, merchant_id=UUID(merchant["id"]), store_id=UUID(store["id"])
            )
        )
        db.commit()
    return user, bearer(login(client, user))


def test_validation_is_read_only_and_confirmation_creates_receipt(client):
    owner, shopper_headers, _, store, item, claimed, data = setup_coupon(client)
    validated = preview(client, owner, data)
    assert validated.status_code == 200, validated.text
    p = validated.json()
    assert p["discount_amount"] == "50.00" and p["payable_amount"] == "200.00"
    assert data["claim_token"] not in validated.text
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "CLAIMED"
        assert db.scalar(select(func.count()).select_from(Redemption)) == 0
    result = confirm(client, owner, data, p)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    assert data["claim_token"] not in result.text and "user_id" not in result.json()
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "REDEEMED"
        assert db.get(Campaign, UUID(item["id"])).claimed_count == 1
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.kind == "coupon.redeemed"))
            == 1
        )
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "COUPON_REDEEMED"))
    wallet = client.get(f"/api/v1/shopper/wallet/{claimed['id']}", headers=shopper_headers).json()
    assert wallet["claim_token"] is None and wallet["status"] == "REDEEMED"
    assert wallet["redemption"]["id"] == result.json()["id"]
    assert len(client.get(f"/api/v1/redemptions?store_id={store['id']}", headers=owner).json()) == 1


@pytest.mark.parametrize("role", [Role.USER, Role.ADMIN, Role.SUPER_ADMIN])
def test_administrative_privileges_do_not_allow_redemption(client, role):
    owner, _, _, _, _, _, data = setup_coupon(client)
    p = preview(client, owner, data).json()
    headers = bearer(login(client, create_user(client, role)))
    assert preview(client, headers, data).status_code == 403
    assert confirm(client, headers, data, p).status_code == 403
    assert (
        client.get(f"/api/v1/redemptions?store_id={data['store_id']}", headers=headers).status_code
        == 403
    )


def test_staff_access_revocation_between_preview_and_confirm(client):
    owner, _, merchant, store, _, claimed, data = setup_coupon(client)
    user, headers = staff(client, merchant, store)
    p = preview(client, headers, data)
    assert p.status_code == 200
    assert (
        client.put(
            f"/api/v1/merchant/staff/{user.id}/assignments",
            headers=owner,
            json={"revision": 1, "store_ids": []},
        ).status_code
        == 204
    )
    assert confirm(client, headers, data, p.json()).status_code == 403
    assert (
        client.get(f"/api/v1/redemptions?store_id={store['id']}", headers=headers).status_code
        == 403
    )
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "CLAIMED"


def test_staff_history_is_own_activity_and_merchant_sees_branch_history(client):
    owner, _, merchant, store, _, _, data = setup_coupon(client)
    _, first = staff(client, merchant, store)
    _, second = staff(client, merchant, store)
    p = preview(client, first, data).json()
    assert confirm(client, first, data, p).status_code == 200
    path = f"/api/v1/redemptions?store_id={store['id']}"
    assert len(client.get(path, headers=first).json()) == 1
    assert client.get(path, headers=second).json() == []
    assert len(client.get(path, headers=owner).json()) == 1


def test_token_and_branch_ownership_are_both_enforced(client):
    from test_locations import located

    owner, _, _, store, _, _, data = setup_coupon(client)
    other, _, other_store = located(client)
    assert preview(client, other, data).status_code == 403
    assert preview(client, other, {**data, "store_id": other_store["id"]}).status_code == 404
    extra = client.post(
        "/api/v1/merchant/stores",
        headers=owner,
        json={"name": "Other branch", "address": "Elsewhere", "city": "Kochi"},
    ).json()
    assert preview(client, owner, {**data, "store_id": extra["id"]}).status_code == 403
    assert preview(client, owner, {**data, "claim_token": "x" * 43}).status_code == 404


@pytest.mark.parametrize(
    "condition",
    [
        "REDEEMED",
        "CANCELLED",
        "EXPIRED",
        "elapsed",
        "inactive_branch",
        "suspended_merchant",
        "closed_now",
        "closed_saved",
    ],
)
def test_confirmation_rechecks_current_and_preserved_conditions(client, condition):
    owner, _, merchant, store, _, claimed, data = setup_coupon(client)
    p = preview(client, owner, data).json()
    closed = [
        {
            "day_of_week": i,
            "is_closed": True,
            "open_time": None,
            "close_time": None,
            "closes_next_day": False,
        }
        for i in range(7)
    ]
    with Session(client.app.state.engine) as db:
        c = db.get(CouponClaim, UUID(claimed["id"]))
        if condition in {"REDEEMED", "EXPIRED", "CANCELLED"}:
            c.status = condition
        elif condition == "elapsed":
            c.claimed_at = datetime.now(UTC) - timedelta(hours=1)
            c.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif condition == "inactive_branch":
            db.get(Store, UUID(store["id"])).status = "INACTIVE"
        elif condition == "suspended_merchant":
            db.get(Merchant, UUID(merchant["id"])).status = "SUSPENDED"
        elif condition == "closed_now":
            db.get(Store, UUID(store["id"])).hours = closed
        else:
            c.snapshot = {
                **c.snapshot,
                "branches": [{**c.snapshot["branches"][0], "hours": closed}],
            }
        db.commit()
    assert confirm(client, owner, data, p).status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Redemption)) == 0


def test_distribution_cancellation_and_offer_edits_preserve_saved_benefit(client):
    from app.offers.models import Offer

    owner, _, _, _, campaign_data, claimed, data = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        c = db.get(Campaign, UUID(campaign_data["id"]))
        c.status = "CANCELLED"
        o = db.get(Offer, c.offer_id)
        o.status = "DRAFT"
        o.discount_value = 5
        db.commit()
    p = preview(client, owner, data)
    assert p.status_code == 200 and p.json()["discount_amount"] == "50.00"
    assert confirm(client, owner, data, p.json()).status_code == 200


@pytest.mark.parametrize(
    "kind,value,purchase,cap,reward,expected",
    [
        ("PERCENTAGE", "15", "123.45", None, None, "18.52"),
        ("PERCENTAGE", "20", "1000", "80", None, "80.00"),
        ("FLAT_AMOUNT", "40", "100", None, None, "40.00"),
        ("SPECIAL_PRICE", "75", "100", None, None, "25.00"),
        ("BOGO", "0", "200", None, "80", "80.00"),
        ("FREE_ITEM", "0", "100", None, "100", "100.00"),
    ],
)
def test_saved_discount_calculation(kind, value, purchase, cap, reward, expected):
    offer = OfferInput(
        **fields(
            str(uuid4()),
            discount_type=kind,
            discount_value=value,
            minimum_purchase="0" if kind != "FLAT_AMOUNT" else "40",
            maximum_discount=cap,
        )
    )
    assert calculate(offer, Decimal(purchase), Decimal(reward) if reward else None) == Decimal(
        expected
    )


@pytest.mark.parametrize(
    "kind,value,purchase,reward",
    [
        ("PERCENTAGE", "20", "10", "2"),
        ("SPECIAL_PRICE", "75", "50", None),
        ("BOGO", "0", "100", "60"),
        ("FREE_ITEM", "0", "10", None),
        ("FREE_ITEM", "0", "10", "20"),
    ],
)
def test_invalid_benefit_inputs(kind, value, purchase, reward):
    offer = OfferInput(
        **fields(
            str(uuid4()),
            discount_type=kind,
            discount_value=value,
            minimum_purchase="0",
            maximum_discount=None,
        )
    )
    with pytest.raises(AuthError):
        calculate(offer, Decimal(purchase), Decimal(reward) if reward else None)


def test_confirmation_binds_actor_and_exact_inputs_and_expires(client):
    owner, _, merchant, store, _, _, data = setup_coupon(client)
    p = preview(client, owner, data).json()
    assert confirm(client, owner, data, p, purchase_amount="500").status_code == 409
    _, assigned = staff(client, merchant, store)
    assert confirm(client, assigned, data, p).status_code == 409
    expired = jwt.encode(
        {
            "sub": "x",
            "purpose": "redeem",
            "claim": "x",
            "request": "x",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        client.app.state.settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    assert confirm(client, owner, data, {**p, "confirmation_token": expired}).status_code == 409
    assert confirm(client, owner, data, p, terms_confirmed=False).status_code == 422
    assert (
        preview(client, {"Authorization": "Bearer " + p["confirmation_token"]}, data).status_code
        == 401
    )


def test_idempotent_retries_return_one_receipt(client):
    owner, _, _, _, _, claimed, data = setup_coupon(client)
    p = preview(client, owner, data).json()
    key = uuid4()
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: confirm(client, owner, data, p, key), range(5)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["id"] for r in results}) == 1
    assert confirm(client, owner, data, p, key, purchase_amount="300").status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Redemption)) == 1
        assert (
            db.scalar(select(func.count()).select_from(Job).where(Job.kind == "coupon.redeemed"))
            == 1
        )


def test_competing_staff_and_owner_redeem_exactly_once(client):
    owner, _, merchant, store, _, _, data = setup_coupon(client)
    _, assigned = staff(client, merchant, store)
    jobs = [
        (owner, preview(client, owner, data).json()),
        (assigned, preview(client, assigned, data).json()),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: confirm(client, item[0], data, item[1]), jobs))
    assert sorted(r.status_code for r in results) == [200, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Redemption)) == 1


def test_outbox_failure_rolls_back_claim_and_receipt(client):
    owner, _, _, _, _, claimed, data = setup_coupon(client)
    p = preview(client, owner, data).json()
    with patch("app.redemptions.router.enqueue", side_effect=RuntimeError("outbox failed")):
        response = confirm(client, owner, data, p)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "outbox failed" not in response.text
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "CLAIMED"
        assert db.scalar(select(func.count()).select_from(Redemption)) == 0
    assert confirm(client, owner, data, p).status_code == 200


def test_request_validation_csrf_rate_limit_and_no_token_echo(client):
    owner, _, _, _, _, _, data = setup_coupon(client)
    for change in (
        {"purchase_amount": "-1"},
        {"purchase_amount": "1.234"},
        {"discount_amount": "1"},
    ):
        r = preview(client, owner, {**data, **change})
        assert r.status_code == 422 and data["claim_token"] not in r.text
    assert preview(client, {**owner, "X-CSRF-Protection": "0"}, data).status_code == 403
    client.app.state.settings.redemption_rate_limit = 1
    assert preview(client, owner, data).status_code == 200
    assert preview(client, owner, data).status_code == 429


def test_same_request_key_cannot_redeem_two_different_claims(client):
    owner, _, _, _, item, _, data = setup_coupon(client)
    _, user_headers = shopper(client)
    second = claim(client, user_headers, item).json()
    with Session(client.app.state.engine) as db:
        second_data = {**data, "claim_token": db.get(CouponClaim, UUID(second["id"])).claim_token}
    first_preview = preview(client, owner, data).json()
    second_preview = preview(client, owner, second_data).json()
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: confirm(client, owner, pair[0], pair[1], key),
                [(data, first_preview), (second_data, second_preview)],
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Redemption)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(CouponClaim).where(CouponClaim.status == "CLAIMED")
            )
            == 1
        )


def test_expiry_worker_and_redemption_share_safe_lock_order(client):
    from app.coupons.service import expire_claim

    owner, _, _, _, _, claimed, data = setup_coupon(client)
    p = preview(client, owner, data).json()

    def expire():
        with Session(client.app.state.engine) as db, db.begin():
            expire_claim(db, {"claim_id": claimed["id"]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        expiry = pool.submit(expire)
        redemption = pool.submit(confirm, client, owner, data, p)
        assert redemption.result(timeout=10).status_code == 200
        expiry.result(timeout=10)
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "REDEEMED"


def test_redemption_outbox_processing_and_receipt_survive_later_branch_edits(client):
    from app.jobs.service import process_one

    owner, user_headers, _, store, _, claimed, data = setup_coupon(client)
    result = confirm(client, owner, data, preview(client, owner, data).json()).json()
    from app.jobs.worker import handlers as worker_handlers

    for _ in range(10):
        if not process_one(client.app.state.engine, worker_handlers()):
            break
    else:
        raise AssertionError("Unexpected unbounded pending work")
    with Session(client.app.state.engine) as db:
        assert db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "COUPON_REDEMPTION_PROCESSED")
        )
        db.get(Store, UUID(store["id"])).name = "Changed name"
        db.commit()
    response = client.get(f"/api/v1/shopper/wallet/{claimed['id']}", headers=user_headers).json()
    assert response["redemption"]["store_name"] == result["store_name"]
    assert response["redemption"]["discount_amount"] == "50.00"
