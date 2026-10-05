from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_locations import located, update_store
from test_profiles import business

from app.auth.models import Role, User
from app.jobs.models import Job
from app.jobs.service import process_one
from app.offers.models import Offer
from app.offers.schemas import OfferInput
from app.offers.service import expire_offer
from app.profiles.models import AuditEvent, Merchant

pytestmark = pytest.mark.integration


def category(client, name="Food & Drink"):
    admin = bearer(login(client, create_user(client, Role.ADMIN)))
    response = client.post(
        "/api/v1/admin/categories", headers=admin, json={"name": name, "description": "Local food"}
    )
    assert response.status_code == 201, response.text
    return admin, response.json()


def fields(category_id, **changes):
    return {
        "category_id": category_id,
        "title": "20% off local lunch",
        "description": "Enjoy a fresh lunch",
        "discount_type": "PERCENTAGE",
        "discount_value": "20.00",
        "minimum_purchase": "100.00",
        "maximum_discount": "80.00",
        "terms_conditions": "Dine-in only. Excludes drinks.",
        "starts_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        **changes,
    }


def action(client, owner, offer, value):
    return client.post(
        f"/api/v1/merchant/offers/{offer['id']}/actions",
        headers=owner,
        json={"action": value, "revision": offer["revision"]},
    )


def review(client, admin, offer, value="APPROVE", note=""):
    return client.post(
        f"/api/v1/admin/offers/{offer['id']}/review",
        headers=admin,
        json={"action": value, "revision": offer["revision"], "note": note},
    )


def edit(client, owner, offer, **changes):
    return client.put(
        f"/api/v1/merchant/offers/{offer['id']}",
        headers=owner,
        json={
            **{key: offer[key] for key in OfferInput.model_fields},
            "revision": offer["revision"],
            **changes,
        },
    )


def fixture_offer(client, approved=True, **changes):
    owner, merchant, store = located(client)
    admin, cat = category(client)
    response = client.post(
        "/api/v1/merchant/offers", headers=owner, json=fields(cat["id"], **changes)
    )
    assert response.status_code == 201, response.text
    offer = response.json()
    if approved:
        submitted = action(client, owner, offer, "SUBMIT")
        assert submitted.status_code == 200, submitted.text
        response = review(client, admin, submitted.json())
        assert response.status_code == 200, response.text
        offer = response.json()
    return owner, admin, merchant, store, cat, offer


def test_category_crud_unique_names_revision_and_audits(client):
    admin, cat = category(client)
    duplicate = client.post(
        "/api/v1/admin/categories", headers=admin, json={"name": "food & drink"}
    )
    assert duplicate.status_code == 409
    updated = client.put(
        f"/api/v1/admin/categories/{cat['id']}",
        headers=admin,
        json={"name": "Dining", "is_active": False, "revision": 1},
    )
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    assert client.get("/api/v1/categories").json() == []
    assert (
        client.put(
            f"/api/v1/admin/categories/{cat['id']}",
            headers=admin,
            json={"name": "Stale", "revision": 1},
        ).status_code
        == 409
    )
    assert (
        client.delete(f"/api/v1/admin/categories/{cat['id']}?revision=1", headers=admin).status_code
        == 409
    )
    assert (
        client.delete(f"/api/v1/admin/categories/{cat['id']}?revision=2", headers=admin).status_code
        == 204
    )
    with Session(client.app.state.engine) as db:
        assert (
            len(list(db.scalars(select(AuditEvent).where(AuditEvent.merchant_id.is_(None))))) == 3
        )


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT, Role.MERCHANT_STAFF])
def test_category_and_offer_review_require_admin(client, role):
    headers = bearer(login(client, create_user(client, role)))
    assert (
        client.post(
            "/api/v1/admin/categories", headers=headers, json={"name": "Denied"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/admin/categories", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/offers", headers=headers).status_code == 403
    assert (
        client.post(
            f"/api/v1/admin/offers/{uuid4()}/review",
            headers=headers,
            json={"action": "APPROVE", "revision": 1},
        ).status_code
        == 403
    )


def test_superadmin_can_manage_categories_and_review(client):
    owner, _, _, _, cat, offer = fixture_offer(client, False)
    admin = bearer(login(client, create_user(client, Role.SUPER_ADMIN)))
    assert client.get("/api/v1/admin/categories", headers=admin).status_code == 200
    offer = action(client, owner, offer, "SUBMIT").json()
    assert review(client, admin, offer).status_code == 200
    assert (
        client.delete(f"/api/v1/admin/categories/{cat['id']}?revision=1", headers=admin).status_code
        == 409
    )


def test_draft_review_public_details_and_audit_privacy(client):
    owner, admin, merchant, store, _, offer = fixture_offer(client, False)
    assert offer["status"] == "DRAFT" and not offer["approved"]
    assert client.get("/api/v1/offers").json()["offers"] == []
    assert client.get(f"/api/v1/offers/{offer['id']}").status_code == 404
    with Session(client.app.state.engine) as db:
        job = db.scalar(select(Job).where(Job.kind == "offer.expire"))
        assert job and job.available_at == datetime.fromisoformat(offer["expires_at"])
    offer = action(client, owner, offer, "SUBMIT").json()
    assert offer["status"] == "PENDING_APPROVAL"
    queue = client.get("/api/v1/admin/offers", headers=admin).json()
    assert queue[0]["business_name"] == merchant["business_name"]
    assert queue[0]["category_name"] == "Food & Drink"
    assert review(client, admin, offer, "REJECT").status_code == 422
    offer = review(client, admin, offer).json()
    response = client.get(f"/api/v1/offers/{offer['id']}?store_id={store['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["maximum_discount"] == "80.00"
    assert response.json()["matched_store_id"] == store["id"]
    assert (
        "merchant_id" not in response.text
        and "moderation_note" not in response.text
        and "approved" not in response.text
    )
    assert response.headers["cache-control"] == "no-store"
    events = client.get(f"/api/v1/admin/offers/{offer['id']}/audit", headers=admin).json()
    assert any(item["detail"].get("decision") == "APPROVE" for item in events)


def test_only_verified_owner_can_create_and_scope_offers(client):
    owner, _, store = business(client, False)
    _, cat = category(client)
    assert (
        client.post("/api/v1/merchant/offers", headers=owner, json=fields(cat["id"])).status_code
        == 409
    )
    owner, _, _ = located(client)
    assert (
        client.post(
            "/api/v1/merchant/offers", headers=owner, json=fields(cat["id"], store_id=store["id"])
        ).status_code
        == 403
    )
    for extra in (
        {"merchant_id": str(uuid4())},
        {"status": "ACTIVE"},
        {"approved": True},
        {"admin_hold": False},
    ):
        assert (
            client.post(
                "/api/v1/merchant/offers", headers=owner, json=fields(cat["id"], **extra)
            ).status_code
            == 422
        )
    staff = bearer(login(client, create_user(client, Role.MERCHANT_STAFF)))
    assert (
        client.post("/api/v1/merchant/offers", headers=staff, json=fields(cat["id"])).status_code
        == 403
    )


def test_cross_merchant_offer_updates_and_actions_are_blocked(client):
    owner, _, _, _, _, offer = fixture_offer(client)
    other, _, _ = located(client)
    assert edit(client, other, offer, title="Stolen offer").status_code == 404
    assert action(client, other, offer, "PAUSE").status_code == 404
    assert client.get("/api/v1/merchant/offers", headers=other).json() == []
    assert client.get("/api/v1/merchant/offers", headers=owner).json()[0]["id"] == offer["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"discount_value": "101"},
        {"discount_value": "0"},
        {"discount_value": "NaN"},
        {"discount_value": "1.234"},
        {"discount_value": "99999999999"},
        {"minimum_purchase": "-1"},
        {"maximum_discount": "0"},
        {
            "discount_type": "FLAT_AMOUNT",
            "discount_value": "200",
            "minimum_purchase": "100",
            "maximum_discount": None,
        },
        {"discount_type": "BOGO", "discount_value": "10", "maximum_discount": None},
        {"discount_type": "FREE_ITEM", "discount_value": "0", "maximum_discount": "10"},
        {"discount_type": "SPECIAL_PRICE", "discount_value": "0", "maximum_discount": None},
        {"starts_at": "2026-01-01T10:00:00"},
        {"expires_at": "2020-01-01T00:00:00Z"},
        {"image_url": "javascript:alert(1)"},
        {"image_url": "https://user:pass@example.com/image.png"},
        {"customer_type": "VIP"},
        {"currency": "USD"},
        {"title": "  "},
    ],
)
def test_invalid_discount_dates_and_fields_rejected(client, changes):
    owner, _, _ = located(client)
    _, cat = category(client)
    assert (
        client.post(
            "/api/v1/merchant/offers", headers=owner, json=fields(cat["id"], **changes)
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "discount,value,minimum",
    [
        ("PERCENTAGE", "100", "0"),
        ("FLAT_AMOUNT", "50", "50"),
        ("BOGO", "0", "0"),
        ("FREE_ITEM", "0", "0"),
        ("SPECIAL_PRICE", "99.50", "0"),
    ],
)
def test_supported_discount_types(client, discount, value, minimum):
    _, _, _, _, _, offer = fixture_offer(
        client,
        False,
        discount_type=discount,
        discount_value=value,
        minimum_purchase=minimum,
        maximum_discount=None,
    )
    assert Decimal(offer["discount_value"]) == Decimal(value)


def test_pause_resume_edit_reapproval_and_archival(client):
    owner, admin, _, _, _, offer = fixture_offer(client)
    paused = action(client, owner, offer, "PAUSE").json()
    assert paused["status"] == "PAUSED"
    assert client.get("/api/v1/offers").json()["offers"] == []
    resumed = action(client, owner, paused, "SUBMIT").json()
    assert resumed["status"] == "ACTIVE"
    edited = edit(client, owner, resumed, discount_value="30").json()
    assert edited["status"] == "DRAFT" and not edited["approved"]
    assert client.get(f"/api/v1/offers/{offer['id']}").status_code == 404
    assert review(client, admin, resumed).status_code == 409
    submitted = action(client, owner, edited, "SUBMIT").json()
    active = review(client, admin, submitted).json()
    archived = action(client, owner, active, "ARCHIVE").json()
    assert archived["status"] == "ARCHIVED"
    assert edit(client, owner, archived).status_code == 409
    assert action(client, owner, archived, "SUBMIT").status_code == 409


def test_rejection_and_admin_hold_cannot_be_bypassed_even_without_moderation(client):
    owner, admin, _, _, _, offer = fixture_offer(client, False)
    offer = action(client, owner, offer, "SUBMIT").json()
    rejected = review(client, admin, offer, "REJECT", "Clarify exclusions").json()
    assert rejected["admin_hold"]
    client.app.state.settings.offer_moderation_enabled = False
    edited = edit(client, owner, rejected, terms_conditions="Corrected exclusions.").json()
    pending = action(client, owner, edited, "SUBMIT").json()
    assert pending["status"] == "PENDING_APPROVAL"
    active = review(client, admin, pending).json()
    suspended = review(client, admin, active, "SUSPEND", "Policy issue").json()
    assert suspended["admin_hold"] and suspended["status"] == "PAUSED"
    assert client.get("/api/v1/offers").json()["offers"] == []
    reactivated = review(client, admin, suspended, "REACTIVATE").json()
    assert reactivated["status"] == "ACTIVE" and not reactivated["admin_hold"]


def test_moderation_disabled_allows_owner_publication(client):
    owner, _, _, _, _, offer = fixture_offer(client, False)
    client.app.state.settings.offer_moderation_enabled = False
    assert action(client, owner, offer, "SUBMIT").json()["status"] == "ACTIVE"
    assert len(client.get("/api/v1/offers").json()["offers"]) == 1


def test_inactive_category_and_branch_hide_offers_and_prevent_publication(client):
    owner, admin, _, store, cat, offer = fixture_offer(client)
    update_store(client, owner, store, status="INACTIVE")
    assert client.get("/api/v1/offers").json()["offers"] == []
    assert client.get(f"/api/v1/offers/{offer['id']}").status_code == 404
    current = client.get("/api/v1/merchant/stores", headers=owner).json()[0]
    update_store(client, owner, current, status="ACTIVE")
    assert len(client.get("/api/v1/offers").json()["offers"]) == 1
    assert (
        client.put(
            f"/api/v1/admin/categories/{cat['id']}",
            headers=admin,
            json={"name": cat["name"], "is_active": False, "revision": cat["revision"]},
        ).status_code
        == 200
    )
    assert client.get("/api/v1/offers").json()["offers"] == []
    paused = action(client, owner, offer, "PAUSE").json()
    assert action(client, owner, paused, "SUBMIT").status_code == 409


def test_unlocated_branch_cannot_publish_and_business_suspension_hides_active_offer(client):
    owner, admin, merchant, store, _, offer = fixture_offer(client, False)
    store = update_store(client, owner, store, latitude=None, longitude=None).json()
    assert action(client, owner, offer, "SUBMIT").status_code == 409
    update_store(client, owner, store, latitude=9.965, longitude=76.242)
    offer = review(client, admin, action(client, owner, offer, "SUBMIT").json()).json()
    with Session(client.app.state.engine) as db:
        db.get(Merchant, UUID(merchant["id"])).status = "SUSPENDED"
        db.commit()
    assert client.get("/api/v1/offers").json()["offers"] == []
    assert edit(client, owner, offer).status_code == 409
    assert (
        action(client, owner, offer, "PAUSE").status_code == 200
    )  # Still able to reduce exposure.


def test_future_and_expired_offers_are_hidden_without_worker(client):
    _, admin, _, _, _, offer = fixture_offer(client)
    with Session(client.app.state.engine) as db:
        stored = db.get(Offer, UUID(offer["id"]))
        stored.starts_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()
    assert client.get("/api/v1/offers").json()["offers"] == []
    with Session(client.app.state.engine) as db:
        stored = db.get(Offer, UUID(offer["id"]))
        stored.starts_at = datetime.now(UTC) - timedelta(hours=2)
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/offers").json()["offers"] == []
    assert client.get(f"/api/v1/offers/{offer['id']}").status_code == 404
    assert (
        client.get("/api/v1/admin/offers?status=EXPIRED", headers=admin).json()[0]["status"]
        == "EXPIRED"
    )
    assert client.get("/api/v1/admin/offers?status=ACTIVE", headers=admin).json() == []


def test_durable_expiry_runs_once_and_stale_jobs_do_not_expire_edited_offer(client):
    owner, _, _, _, _, offer = fixture_offer(client)
    with Session(client.app.state.engine) as db:
        stored = db.get(Offer, UUID(offer["id"]))
        old_payload = {"offer_id": offer["id"], "expires_at": stored.expires_at.isoformat()}
    later = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    edited = edit(client, owner, offer, expires_at=later).json()
    with Session(client.app.state.engine) as db, db.begin():
        expire_offer(db, old_payload)
    with Session(client.app.state.engine) as db:
        stored = db.get(Offer, UUID(offer["id"]))
        assert stored.status == "DRAFT"
        expiry = datetime.now(UTC) - timedelta(seconds=1)
        stored.expires_at = expiry
        job = db.scalar(select(Job).order_by(Job.available_at.desc()).limit(1))
        job.payload = {"offer_id": offer["id"], "expires_at": expiry.isoformat()}
        job.available_at = expiry
        db.commit()
    from app.jobs.worker import handlers as worker_handlers

    for _ in range(10):
        if not process_one(client.app.state.engine, worker_handlers()):
            break
    else:
        raise AssertionError("Unexpected unbounded pending work")
    with Session(client.app.state.engine) as db:
        stored = db.get(Offer, UUID(offer["id"]))
        assert stored.status == "EXPIRED" and stored.revision == edited["revision"] + 1
        assert (
            len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "OFFER_EXPIRED"))))
            == 1
        )
    assert not process_one(client.app.state.engine, worker_handlers())


def test_nearby_offer_deduplication_category_search_and_branch_scope(client):
    owner, admin, _, store, cat, offer = fixture_offer(client)
    second = client.post(
        "/api/v1/merchant/stores",
        headers=owner,
        json={
            "name": "Nearby branch",
            "city": "Kochi",
            "address": "Nearby Road",
            "latitude": 9.97,
            "longitude": 76.242,
        },
    ).json()
    far = client.post(
        "/api/v1/merchant/stores",
        headers=owner,
        json={
            "name": "Far branch",
            "city": "Kochi",
            "address": "Far Road",
            "latitude": 10.97,
            "longitude": 76.242,
        },
    ).json()
    response = client.get("/api/v1/offers?latitude=9.965&longitude=76.242").json()
    assert len(response["offers"]) == 1
    assert response["offers"][0]["matched_store_id"] == store["id"]
    assert response["offers"][0]["distance_meters"] == 0
    assert len(client.get("/api/v1/offers").json()["offers"]) == 1
    assert client.get(f"/api/v1/offers?category_id={uuid4()}").json()["offers"] == []
    assert client.get(f"/api/v1/offers?category_id={cat['id']}&q=lunch").json()["offers"]
    assert client.get("/api/v1/offers?q=%25%25").json()["offers"] == []
    assert client.get(f"/api/v1/offers/{offer['id']}?store_id={second['id']}").status_code == 200
    scoped = edit(client, owner, offer, store_id=far["id"]).json()
    scoped = review(client, admin, action(client, owner, scoped, "SUBMIT").json()).json()
    assert client.get("/api/v1/offers?latitude=9.965&longitude=76.242").json()["offers"] == []
    assert client.get(f"/api/v1/offers/{offer['id']}?store_id={store['id']}").status_code == 404
    assert len(client.get("/api/v1/offers").json()["offers"]) == 1


def test_public_pagination_and_invalid_location_inputs(client):
    owner, admin, _, _, cat, _ = fixture_offer(client)
    for title in ("Second offer", "Third offer"):
        offer = client.post(
            "/api/v1/merchant/offers", headers=owner, json=fields(cat["id"], title=title)
        ).json()
        review(client, admin, action(client, owner, offer, "SUBMIT").json())
    ids, offset = [], 0
    while offset is not None:
        response = client.get(f"/api/v1/offers?limit=1&offset={offset}").json()
        ids += [item["id"] for item in response["offers"]]
        offset = response["next_offset"]
    assert len(ids) == len(set(ids)) == 3
    for query in (
        "latitude=1",
        "latitude=NaN&longitude=1",
        "radius_km=5",
        "latitude=0&longitude=0&radius_km=20",
        "limit=100",
        "offset=-1",
    ):
        assert client.get("/api/v1/offers?" + query).status_code == 422


def test_concurrent_reviews_have_one_winner(client):
    owner, admin, _, _, _, offer = fixture_offer(client, False)
    offer = action(client, owner, offer, "SUBMIT").json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: review(client, admin, offer).status_code, range(2))) == [
            200,
            409,
        ]


def test_concurrent_edits_and_category_delete_reference_safety(client):
    owner, admin, _, _, cat, offer = fixture_offer(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(
            pool.map(
                lambda n: edit(client, owner, offer, title=f"Edited offer {n}").status_code,
                range(2),
            )
        ) == [200, 409]
    assert (
        client.delete(f"/api/v1/admin/categories/{cat['id']}?revision=1", headers=admin).status_code
        == 409
    )


def test_csrf_and_inactive_owner_protection(client):
    owner, _, merchant, _, _, offer = fixture_offer(client)
    assert (
        client.post(
            f"/api/v1/merchant/offers/{offer['id']}/actions",
            headers={**owner, "X-CSRF-Protection": "0"},
            json={"action": "PAUSE", "revision": offer["revision"]},
        ).status_code
        == 403
    )
    with Session(client.app.state.engine) as db:
        merchant_row = db.get(Merchant, UUID(merchant["id"]))
        db.get(User, merchant_row.owner_id).is_active = False
        db.commit()
    assert client.get("/api/v1/offers").json()["offers"] == []
    assert action(client, owner, offer, "PAUSE").status_code == 401
