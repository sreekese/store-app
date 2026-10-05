from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_auth import PASSWORD, bearer, create_user, login

from app.auth.models import Role, User
from app.auth.security import token_hash, verify_password
from app.profiles.models import Invitation, StaffAssignment

pytestmark = pytest.mark.integration
BUSINESS = {
    "business_name": "Neighbourhood Café",
    "category": "Café",
    "description": "Fresh local food",
    "contact_email": "cafe@example.com",
    "phone": "+91 9876543210",
}


def business(client, approved=True):
    owner = create_user(client, Role.MERCHANT)
    headers = bearer(login(client, owner))
    response = client.put("/api/v1/merchant/profile", headers=headers, json=BUSINESS)
    assert response.status_code == 200, response.text
    merchant = response.json()
    if approved:
        admin = bearer(login(client, create_user(client, Role.ADMIN)))
        response = client.put(
            f"/api/v1/admin/merchants/{merchant['id']}/review",
            headers=admin,
            json={"status": "VERIFIED", "revision": merchant["revision"]},
        )
        assert response.status_code == 200, response.text
        merchant = response.json()
    store = client.post(
        "/api/v1/merchant/stores",
        headers=headers,
        json={"name": "Central branch", "address": "12 Market Road", "city": "Kochi"},
    )
    assert store.status_code == 201, store.text
    return headers, merchant, store.json()


def invite(client, headers, store, email=None):
    response = client.post(
        "/api/v1/merchant/invitations",
        headers=headers,
        json={"email": email or f"{uuid4().hex}@example.com", "store_ids": [store["id"]]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def accept(client, invitation, password=PASSWORD):
    return client.post(
        "/api/v1/staff/invitations/accept",
        json={"token": invitation["token"], "display_name": "New Staff", "password": password},
    )


def staff_session(client, invitation):
    accepted = accept(client, invitation)
    assert accepted.status_code == 200, accepted.text
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": accepted.json()["email"],
            "password": PASSWORD,
            "workspace": "MERCHANT_STAFF",
        },
    )
    assert response.status_code == 200
    return bearer(response), accepted.json()


def test_shopper_profile_persists_and_is_private(client):
    shopper = create_user(client)
    headers = bearer(login(client, shopper))
    data = {
        "display_name": "  Neha  ",
        "phone": "+91 1234567890",
        "city": "Kochi",
        "area": "Fort Kochi",
        "postal_code": "682001",
        "location_preference": "GPS",
    }
    result = client.put("/api/v1/profile", headers=headers, json=data)
    assert result.status_code == 200
    assert result.json()["display_name"] == "Neha"
    assert result.json()["email"] == shopper.email
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/auth/me", headers=headers).json()["display_name"] == "Neha"
    assert client.get("/api/v1/profile", headers=headers).json()["city"] == "Kochi"
    other = bearer(login(client, create_user(client)))
    assert client.get("/api/v1/profile", headers=other).json()["city"] == ""
    assert client.get("/api/v1/profile").status_code == 401


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "ADMIN"},
        {"email": "new@example.com"},
        {"user_id": str(uuid4())},
        {"location_preference": "UNKNOWN"},
        {"display_name": "  "},
        {"phone": "<script>"},
    ],
)
def test_profile_rejects_privileged_or_invalid_fields(client, extra):
    headers = bearer(login(client, create_user(client)))
    assert (
        client.put(
            "/api/v1/profile", headers=headers, json={"display_name": "Name", **extra}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT_STAFF, Role.ADMIN, Role.SUPER_ADMIN])
def test_only_owner_role_can_submit_business(client, role):
    headers = bearer(login(client, create_user(client, role)))
    assert client.put("/api/v1/merchant/profile", headers=headers, json=BUSINESS).status_code == 403


def test_owner_cannot_self_verify_or_spoof_ownership(client):
    owner = bearer(login(client, create_user(client, Role.MERCHANT)))
    for extra in ({"status": "VERIFIED"}, {"owner_id": str(uuid4())}, {"review_note": "approved"}):
        assert (
            client.put(
                "/api/v1/merchant/profile", headers=owner, json={**BUSINESS, **extra}
            ).status_code
            == 422
        )
    owner, merchant, _ = business(client, False)
    assert (
        client.put(
            f"/api/v1/admin/merchants/{merchant['id']}/review",
            headers=owner,
            json={"status": "VERIFIED", "revision": 1},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("role", [Role.ADMIN, Role.SUPER_ADMIN])
def test_review_workflow_requires_reason_tracks_revision_and_audit(client, role):
    owner, merchant, _ = business(client, False)
    reviewer = bearer(login(client, create_user(client, role)))
    path = f"/api/v1/admin/merchants/{merchant['id']}/review"
    assert (
        client.put(path, headers=reviewer, json={"status": "REJECTED", "revision": 1}).status_code
        == 422
    )
    response = client.put(
        path,
        headers=reviewer,
        json={"status": "REJECTED", "revision": 1, "note": "Business contact needs correction"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert (
        client.get("/api/v1/merchant/profile", headers=owner).json()["review_note"]
        == "Business contact needs correction"
    )
    updated = client.put("/api/v1/merchant/profile", headers=owner, json=BUSINESS).json()
    assert updated["status"] == "PENDING" and updated["revision"] == 3
    assert (
        client.put(path, headers=reviewer, json={"status": "VERIFIED", "revision": 1}).status_code
        == 409
    )
    assert (
        client.put(
            path, headers=reviewer, json={"status": "UNDER_REVIEW", "revision": 3}
        ).status_code
        == 200
    )
    assert (
        client.put(path, headers=reviewer, json={"status": "VERIFIED", "revision": 4}).status_code
        == 200
    )
    assert (
        client.put(path, headers=reviewer, json={"status": "VERIFIED", "revision": 5}).status_code
        == 409
    )
    events = client.get(f"/api/v1/admin/merchants/{merchant['id']}/audit", headers=reviewer).json()
    assert sum(e["action"] == "MERCHANT_REVIEWED" for e in events) == 3
    assert all("token" not in str(event) and "password" not in str(event) for event in events)
    assert (
        client.get("/api/v1/admin/merchants?status=VERIFIED", headers=reviewer).json()[0]["id"]
        == merchant["id"]
    )
    assert client.get("/api/v1/admin/merchants?status=PENDING", headers=reviewer).json() == []
    assert client.get("/api/v1/admin/merchants?offset=-1", headers=reviewer).status_code == 422


def test_unverified_business_cannot_invite(client):
    owner, _, store = business(client, False)
    response = client.post(
        "/api/v1/merchant/invitations",
        headers=owner,
        json={"email": "staff@example.com", "store_ids": [store["id"]]},
    )
    assert response.status_code == 409


def test_invitation_token_hashed_email_bound_single_use_and_login(client):
    owner, merchant, store = business(client)
    invitation = invite(client, owner, store, "Staff@Example.com")
    with Session(client.app.state.engine) as db:
        row = db.get(Invitation, UUID(invitation["invitation"]["id"]))
        assert row.token_hash == token_hash(invitation["token"])
        assert row.email == "staff@example.com"
    listing = client.get("/api/v1/merchant/invitations", headers=owner)
    assert invitation["token"] not in listing.text and "token_hash" not in listing.text
    preview = client.post("/api/v1/staff/invitations/preview", json={"token": invitation["token"]})
    assert preview.json()["business_name"] == merchant["business_name"]
    assert preview.headers["cache-control"] == "no-store"
    assert (
        client.post(
            "/api/v1/staff/invitations/accept",
            json={
                "token": invitation["token"],
                "display_name": "Bad",
                "password": PASSWORD,
                "email": "attacker@example.com",
            },
        ).status_code
        == 422
    )
    staff, user = staff_session(client, invitation)
    assert user["email"] == "staff@example.com" and user["role"] == "MERCHANT_STAFF"
    assert "password" not in str(user)
    assert accept(client, invitation).status_code == 410
    assert client.get("/api/v1/staff/stores", headers=staff).json()[0]["id"] == store["id"]
    assert client.get(f"/api/v1/staff/stores/{store['id']}", headers=staff).status_code == 200
    with Session(client.app.state.engine) as db:
        stored = db.get(User, UUID(user["id"]))
        assert verify_password(PASSWORD, stored.password_hash)


def test_cross_merchant_access_and_assignment_rejected(client):
    owner, _, store = business(client)
    other, _, other_store = business(client)
    assert client.get("/api/v1/merchant/stores", headers=owner).json() == [store]
    assert (
        client.post(
            "/api/v1/merchant/invitations",
            headers=owner,
            json={"email": "staff@example.com", "store_ids": [other_store["id"]]},
        ).status_code
        == 403
    )
    invitation = invite(client, owner, store)
    assert (
        client.delete(
            f"/api/v1/merchant/invitations/{invitation['invitation']['id']}", headers=other
        ).status_code
        == 404
    )
    staff, person = staff_session(client, invitation)
    assert client.get(f"/api/v1/staff/stores/{other_store['id']}", headers=staff).status_code == 403
    path = f"/api/v1/merchant/staff/{person['id']}/assignments"
    assert (
        client.put(
            path, headers=owner, json={"revision": 1, "store_ids": [other_store["id"]]}
        ).status_code
        == 403
    )
    assert (
        client.put(
            path, headers=other, json={"revision": 1, "store_ids": [other_store["id"]]}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/merchant/staff", headers=other).json() == []
    assert client.get("/api/v1/admin/merchants", headers=staff).status_code == 403
    assert client.get("/api/v1/profile", headers=staff).status_code == 403


def test_reassignment_and_revocation_effective_without_relogin(client):
    owner, _, store = business(client)
    second = client.post(
        "/api/v1/merchant/stores",
        headers=owner,
        json={"name": "Second branch", "address": "15 Lake Road", "city": "Kochi"},
    ).json()
    staff, person = staff_session(client, invite(client, owner, store))
    path = f"/api/v1/merchant/staff/{person['id']}/assignments"
    assert (
        client.put(
            path, headers=owner, json={"revision": 1, "store_ids": [second["id"]]}
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/staff/stores/{store['id']}", headers=staff).status_code == 403
    assert client.get(f"/api/v1/staff/stores/{second['id']}", headers=staff).status_code == 200
    assert client.put(path, headers=owner, json={"revision": 2, "store_ids": []}).status_code == 204
    assert client.get(f"/api/v1/staff/stores/{second['id']}", headers=staff).status_code == 403
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []
    assert client.get("/api/v1/auth/me", headers=staff).status_code == 200


def test_existing_staff_requires_password_and_retains_other_business_access(client):
    owner, _, store = business(client)
    staff, person = staff_session(client, invite(client, owner, store))
    second_owner, _, second_store = business(client)
    invitation = invite(client, second_owner, second_store, person["email"])
    assert accept(client, invitation, "wrong-staff-password").status_code == 403
    assert accept(client, invitation).status_code == 200
    assert len(client.get("/api/v1/staff/stores", headers=staff).json()) == 2
    assert (
        client.put(
            f"/api/v1/merchant/staff/{person['id']}/assignments",
            headers=owner,
            json={"revision": 1, "store_ids": []},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/staff/stores", headers=staff).json() == [second_store]
    with Session(client.app.state.engine) as db:
        assert db.get(User, UUID(person["id"])).display_name == "New Staff"


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT, Role.ADMIN, Role.SUPER_ADMIN])
def test_existing_nonstaff_accounts_cannot_be_converted(client, role):
    owner, _, store = business(client)
    user = create_user(client, role)
    assert (
        client.post(
            "/api/v1/merchant/invitations",
            headers=owner,
            json={"email": user.email, "store_ids": [store["id"]]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("mode", ["expired", "cancelled", "reissued"])
def test_closed_links_cannot_be_previewed_or_accepted(client, mode):
    owner, _, store = business(client)
    invitation = invite(client, owner, store)
    if mode == "expired":
        with Session(client.app.state.engine) as db:
            row = db.get(Invitation, UUID(invitation["invitation"]["id"]))
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
    elif mode == "cancelled":
        assert (
            client.delete(
                f"/api/v1/merchant/invitations/{invitation['invitation']['id']}", headers=owner
            ).status_code
            == 204
        )
    else:
        invite(client, owner, store, invitation["invitation"]["email"])
    assert accept(client, invitation).status_code == 410
    assert (
        client.post(
            "/api/v1/staff/invitations/preview", json={"token": invitation["token"]}
        ).status_code
        == 410
    )


def test_suspension_blocks_staff_and_invite_acceptance_and_owner_bypass(client):
    owner, merchant, store = business(client)
    staff, person = staff_session(client, invite(client, owner, store))
    pending = invite(client, owner, store)
    admin = bearer(login(client, create_user(client, Role.ADMIN)))
    assert (
        client.put(
            f"/api/v1/admin/merchants/{merchant['id']}/review",
            headers=admin,
            json={
                "status": "SUSPENDED",
                "note": "Verification issue",
                "revision": merchant["revision"],
            },
        ).status_code
        == 200
    )
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []
    assert accept(client, pending).status_code == 409
    assert client.put("/api/v1/merchant/profile", headers=owner, json=BUSINESS).status_code == 409
    assert (
        client.put(
            f"/api/v1/merchant/staff/{person['id']}/assignments",
            headers=owner,
            json={"revision": 1, "store_ids": []},
        ).status_code
        == 204
    )


def test_editing_verified_profile_pauses_staff_and_resubmits(client):
    owner, _, store = business(client)
    staff, _ = staff_session(client, invite(client, owner, store))
    result = client.put(
        "/api/v1/merchant/profile",
        headers=owner,
        json={**BUSINESS, "business_name": "Changed Business"},
    )
    assert result.json()["status"] == "PENDING"
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []


def test_concurrent_invitation_acceptance_is_atomic(client):
    owner, _, store = business(client)
    invitation = invite(client, owner, store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: accept(client, invitation).status_code, range(2)))
    assert sorted(statuses) == [200, 410]
    with Session(client.app.state.engine) as db:
        assert len(list(db.scalars(select(StaffAssignment)))) == 1


def test_concurrent_reviews_detect_stale_revision(client):
    _, merchant, _ = business(client, False)
    admin = bearer(login(client, create_user(client, Role.ADMIN)))

    def approve(_):
        return client.put(
            f"/api/v1/admin/merchants/{merchant['id']}/review",
            headers=admin,
            json={"status": "VERIFIED", "revision": 1},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(approve, range(2))) == [200, 409]


def test_invitation_validation_and_csrf(client):
    owner, _, store = business(client)
    for ids in ([], [store["id"], store["id"]], ["not-a-uuid"]):
        assert (
            client.post(
                "/api/v1/merchant/invitations",
                headers=owner,
                json={"email": "staff@example.com", "store_ids": ids},
            ).status_code
            == 422
        )
    invitation = invite(client, owner, store)
    assert (
        client.post(
            "/api/v1/staff/invitations/accept",
            headers={"X-CSRF-Protection": "0"},
            json={"token": invitation["token"], "display_name": "Name", "password": PASSWORD},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/staff/invitations/accept",
            json={"token": invitation["token"], "display_name": "Name", "password": "short"},
        ).status_code
        == 422
    )


def test_manual_assignment_change_invalidates_outstanding_staff_invites(client):
    owner, _, store = business(client)
    staff, person = staff_session(client, invite(client, owner, store))
    pending = invite(client, owner, store, person["email"])
    assert (
        client.put(
            f"/api/v1/merchant/staff/{person['id']}/assignments",
            headers=owner,
            json={"revision": 1, "store_ids": []},
        ).status_code
        == 204
    )
    assert accept(client, pending).status_code == 410
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.com"]
)
def test_business_links_reject_unsafe_schemes_and_credentials(client, url):
    owner = bearer(login(client, create_user(client, Role.MERCHANT)))
    assert (
        client.put(
            "/api/v1/merchant/profile", headers=owner, json={**BUSINESS, "website": url}
        ).status_code
        == 422
    )


def test_business_links_saved_and_shown_to_reviewer(client):
    owner, merchant, _ = business(client, False)
    links = {
        "website": "https://example.com/",
        "logo_url": "https://example.com/logo.png",
        "cover_image_url": "https://example.com/cover.jpg",
    }
    saved = client.put("/api/v1/merchant/profile", headers=owner, json={**BUSINESS, **links})
    assert saved.status_code == 200
    assert all(saved.json()[key] == value for key, value in links.items())
    admin = bearer(login(client, create_user(client, Role.ADMIN)))
    reviewed = client.get("/api/v1/admin/merchants", headers=admin).json()[0]
    assert reviewed["id"] == merchant["id"]
    assert reviewed["website"] == links["website"]


def test_invitation_password_attempts_are_rate_limited(client):
    owner, _, store = business(client)
    existing = create_user(client, Role.MERCHANT_STAFF)
    invitation = invite(client, owner, store, existing.email)
    for _ in range(10):
        assert accept(client, invitation, "incorrect-long-password").status_code == 403
    assert accept(client, invitation, "incorrect-long-password").status_code == 429
