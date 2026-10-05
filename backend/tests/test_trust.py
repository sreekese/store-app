from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_redemptions import confirm, preview, setup_coupon, staff

from app.auth.models import Role
from app.coupons.models import CouponClaim
from app.profiles.models import AuditEvent, Merchant, StaffAssignment, Store
from app.redemptions.models import Redemption
from app.trust.models import CaseAction

pytestmark = pytest.mark.integration
BASE = "/api/v1/trust"


def admin(client, role=Role.ADMIN):
    return bearer(login(client, create_user(client, role)))


def redeemed(client):
    fixture = setup_coupon(client)
    receipt = confirm(
        client, fixture[0], fixture[6], preview(client, fixture[0], fixture[6]).json()
    )
    assert receipt.status_code == 200
    return fixture, receipt.json()


def review(client, headers, receipt, **changes):
    return client.post(
        BASE + "/reviews",
        headers=headers,
        json={
            "redemption_id": receipt["id"],
            "rating": 4,
            "comment": "Helpful staff and good value.",
            **changes,
        },
    )


def report(client, fixture, headers=None, **changes):
    return client.post(
        BASE + "/cases",
        headers=headers or fixture[1],
        json={
            "target_type": "CLAIM",
            "target_id": fixture[5]["id"],
            "store_id": fixture[3]["id"],
            "reason": "STORE_REFUSED_COUPON",
            "description": "The store did not honour the saved offer.",
            **changes,
        },
    )


def test_review_requires_owned_successful_redemption_and_is_unique(client):
    f = setup_coupon(client)
    assert review(client, f[1], f[5]).status_code == 404
    r = confirm(client, f[0], f[6], preview(client, f[0], f[6]).json()).json()
    other = admin(client, Role.USER)
    assert review(client, other, r).status_code == 404
    assert client.get(BASE + "/reviews/mine/" + r["id"], headers=other).status_code == 404
    result = review(client, f[1], r)
    assert result.status_code == 201 and result.json()["status"] == "PENDING"
    assert review(client, f[1], r).status_code == 409
    assert (
        client.get(BASE + "/reviews/mine/" + r["id"], headers=f[1]).json()["review"]["id"]
        == result.json()["id"]
    )
    assert "redemption_id" not in result.json()


@pytest.mark.parametrize(
    "changes",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": 1.5},
        {"rating": True},
        {"comment": "   "},
        {"comment": "x" * 2001},
        {"user_id": str(uuid4())},
    ],
)
def test_review_validation(client, changes):
    user = admin(client, Role.USER)
    assert review(client, user, {"id": str(uuid4())}, **changes).status_code == 422


@pytest.mark.parametrize("role", [Role.MERCHANT, Role.MERCHANT_STAFF, Role.ADMIN, Role.SUPER_ADMIN])
def test_management_cannot_submit_shopper_reviews_or_reports(client, role):
    headers = admin(client, role)
    assert review(client, headers, {"id": str(uuid4())}).status_code == 403
    assert (
        client.post(
            BASE + "/cases",
            headers=headers,
            json={
                "target_type": "STORE",
                "target_id": str(uuid4()),
                "store_id": str(uuid4()),
                "reason": "OTHER",
                "description": "An issue at the store.",
            },
        ).status_code
        == 403
    )


def test_moderation_aggregates_only_published_reviews_and_audits(client):
    f, receipt = redeemed(client)
    r = review(client, f[1], receipt).json()
    path = BASE + f"/reviews?store_id={f[3]['id']}&offer_id={f[4]['offer_id']}"
    assert client.get(path).json()["count"] == 0
    a = admin(client)
    assert client.get(BASE + "/reviews/moderation", headers=f[0]).status_code == 403
    assert len(client.get(BASE + "/reviews/moderation", headers=a).json()["items"]) == 1
    change = {
        "revision": 1,
        "status": "PUBLISHED",
        "reason": "Verified experience, no personal data.",
    }
    url = BASE + f"/reviews/{r['id']}/moderate"
    assert client.post(url, headers=f[0], json=change).status_code == 403
    assert client.post(url, headers=a, json=change).status_code == 200
    assert client.post(url, headers=a, json=change).status_code == 409
    public = client.get(path)
    assert public.json()["count"] == 1 and public.json()["average"] == 4
    assert all(
        s not in public.text
        for s in ["user_id", "redemption_id", "moderation_reason", f[6]["claim_token"]]
    )
    assert (
        client.post(
            url,
            headers=a,
            json={"revision": 2, "status": "HIDDEN", "reason": "Content reported and removed."},
        ).status_code
        == 200
    )
    assert client.get(path).json()["count"] == 0
    with Session(client.app.state.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "REVIEW_MODERATED")
            )
            == 2
        )


def test_concurrent_duplicate_reviews_create_only_one(client):
    f, r = redeemed(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: review(client, f[1], r).status_code, range(2)))
    assert sorted(results) == [201, 409]


def test_claim_reports_validate_ownership_branch_and_duplicates(client):
    f = setup_coupon(client)
    other = admin(client, Role.USER)
    assert report(client, f, headers=other).status_code == 404
    assert report(client, f, store_id=str(uuid4())).status_code == 404
    assert report(client, f, description="   ").status_code == 422
    result = report(client, f)
    assert result.status_code == 201
    assert result.headers["cache-control"] == "no-store"
    assert f[6]["claim_token"] not in result.text
    assert "claim_token" not in result.text
    assert result.json()["context"]["offer"]["terms_conditions"]
    assert report(client, f).status_code == 409


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT, Role.MERCHANT_STAFF])
def test_other_accounts_cannot_read_respond_or_resolve_cases(client, role):
    f = setup_coupon(client)
    row = report(client, f).json()
    headers = admin(client, role)
    url = BASE + "/cases/" + row["id"]
    assert client.get(BASE + "/cases", headers=headers).json()["items"] == []
    assert client.get(url, headers=headers).status_code == 404
    assert client.get(url + "/history", headers=headers).status_code == 404
    assert (
        client.post(
            url + "/respond", headers=headers, json={"revision": 1, "message": "Unauthorized"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            url + "/transition",
            headers=headers,
            json={"revision": 1, "message": "Unauthorized", "status": "UNDER_REVIEW"},
        ).status_code
        == 403
    )


def test_assigned_staff_access_is_revoked_when_assignment_removed(client):
    f = setup_coupon(client)
    user, headers = staff(client, f[2], f[3])
    row = report(client, f).json()
    url = BASE + "/cases/" + row["id"]
    assert client.get(url, headers=headers).status_code == 200
    assert (
        client.post(
            url + "/respond",
            headers=headers,
            json={"revision": 1, "message": "We are checking the issue."},
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        db.execute(delete(StaffAssignment).where(StaffAssignment.staff_id == user.id))
        db.commit()
    assert client.get(url, headers=headers).status_code == 404


def test_full_resolution_history_preserves_coupon_and_receipt(client):
    f, r = redeemed(client)
    row = report(client, f, reason="INCORRECT_DISCOUNT").json()
    url = BASE + "/cases/" + row["id"]
    a = admin(client, Role.SUPER_ADMIN)
    assert row["redemption_id"] == r["id"]
    assert row["context"]["receipt"]["discount_amount"] == "50.00"
    assert (
        client.post(
            url + "/transition",
            headers=a,
            json={"revision": 1, "status": "RESOLVED", "message": "Skip review"},
        ).status_code
        == 409
    )
    for version, state in [(1, "UNDER_REVIEW"), (2, "AWAITING_RESPONSE")]:
        assert (
            client.post(
                url + "/transition",
                headers=a,
                json={"revision": version, "status": state, "message": "Please check the receipt."},
            ).status_code
            == 200
        )
    assert (
        client.post(
            url + "/respond",
            headers=f[0],
            json={"revision": 3, "message": "The benefit was correctly applied."},
        ).status_code
        == 200
    )
    assert (
        client.post(
            url + "/respond", headers=f[1], json={"revision": 3, "message": "Stale response"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            url + "/respond",
            headers=f[1],
            json={"revision": 4, "message": "Thank you, I can confirm."},
        ).status_code
        == 200
    )
    assert (
        client.post(
            url + "/transition",
            headers=a,
            json={
                "revision": 5,
                "status": "RESOLVED",
                "message": "Receipt checked with both parties.",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            url + "/respond", headers=f[1], json={"revision": 6, "message": "No reopen"}
        ).status_code
        == 409
    )
    result = client.get(url, headers=f[1]).json()
    assert result["resolved_at"] and result["resolution"] == "Receipt checked with both parties."
    history = client.get(url + "/history", headers=f[1]).json()["items"]
    assert len(history) == 6 and history[0]["status"] == "RESOLVED"
    assert "actor_id" not in history[0]
    with Session(client.app.state.engine) as db:
        claim = db.get(CouponClaim, UUID(f[5]["id"]))
        receipt = db.get(Redemption, UUID(r["id"]))
        assert claim.status == "REDEEMED" and str(receipt.discount_amount) == "50.00"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("SUPPORT_%"))
            )
            == 6
        )


def test_reports_remain_available_for_suspended_business_and_expired_claim(client):
    f = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        db.get(Merchant, UUID(f[2]["id"])).status = "SUSPENDED"
        db.get(Store, UUID(f[3]["id"])).status = "INACTIVE"
        db.get(CouponClaim, UUID(f[5]["id"])).status = "EXPIRED"
        db.commit()
    row = report(client, f)
    assert row.status_code == 201
    assert client.get(BASE + "/cases/" + row.json()["id"], headers=f[0]).status_code == 200


def test_offer_store_and_review_reports_validate_visible_targets(client):
    f, r = redeemed(client)
    for target, id in [("OFFER", f[4]["offer_id"]), ("STORE", f[3]["id"])]:
        assert (
            report(client, f, target_type=target, target_id=id, reason="OTHER").status_code == 201
        )
        assert (
            report(
                client, f, target_type=target, target_id=str(uuid4()), reason="OTHER"
            ).status_code
            == 404
        )
    assert report(client, f, target_type="STORE", target_id=f[3]["id"]).status_code == 422
    review_row = review(client, f[1], r).json()
    assert (
        report(
            client,
            f,
            target_type="REVIEW",
            target_id=review_row["id"],
            reason="INAPPROPRIATE_CONTENT",
        ).status_code
        == 404
    )
    a = admin(client)
    client.post(
        BASE + f"/reviews/{review_row['id']}/moderate",
        headers=a,
        json={"revision": 1, "status": "PUBLISHED", "reason": "Approved"},
    )
    assert (
        report(
            client,
            f,
            target_type="REVIEW",
            target_id=review_row["id"],
            reason="INAPPROPRIATE_CONTENT",
        ).status_code
        == 201
    )


def test_concurrent_responses_require_current_revision(client):
    f = setup_coupon(client)
    row = report(client, f).json()
    url = BASE + f"/cases/{row['id']}/respond"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: (
                    client.post(
                        url, headers=f[0], json={"revision": 1, "message": "Store response"}
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409]


def test_case_and_history_pagination_filters_and_validation(client):
    f = setup_coupon(client)
    row = report(client, f).json()
    url = BASE + f"/cases/{row['id']}"
    with Session(client.app.state.engine) as db:
        for n in range(2, 25):
            db.add(
                CaseAction(
                    case_id=UUID(row["id"]),
                    actor_role="USER",
                    kind="RESPONSE",
                    message="Follow up",
                    status="OPEN",
                    revision=n,
                )
            )
        db.commit()
    first = client.get(url + "/history", headers=f[1]).json()
    assert len(first["items"]) == 20 and first["next_offset"] == 20
    assert len(client.get(url + "/history?offset=20", headers=f[1]).json()["items"]) == 4
    assert client.get(BASE + "/cases?status=RESOLVED", headers=f[1]).json()["items"] == []
    assert client.get(BASE + "/cases?status=INVALID", headers=f[1]).status_code == 422
    assert client.get(BASE + "/cases?offset=-1", headers=f[1]).status_code == 422
    assert client.get(BASE + "/cases").status_code == 401
