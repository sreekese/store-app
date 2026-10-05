from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_profiles import accept, business, invite, staff_session

from app.auth.models import Role, User
from app.profiles.models import (
    AuditEvent,
    Invitation,
    Merchant,
    StaffAccess,
    StaffAssignment,
    Store,
)

pytestmark = pytest.mark.integration


def roster(client, owner):
    r = client.get("/api/v1/merchant/staff", headers=owner)
    assert r.status_code == 200
    return r.json()


def update(client, owner, person, stores, revision=1):
    return client.put(
        f"/api/v1/merchant/staff/{person['id']}/assignments",
        headers=owner,
        json={"revision": revision, "store_ids": stores},
    )


def team(client):
    owner, merchant, store = business(client)
    invitation = invite(client, owner, store)
    staff, person = staff_session(client, invitation)
    return owner, merchant, store, staff, person, invitation


def test_revoked_staff_remain_in_roster_and_can_be_restored(client):
    owner, _, store, staff, person, _ = team(client)
    assert roster(client, owner)[0]["revision"] == 1
    assert update(client, owner, person, []).status_code == 204
    row = roster(client, owner)[0]
    assert row["store_ids"] == [] and row["revision"] == 2 and row["account_active"]
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []
    assert update(client, owner, person, [store["id"]], 2).status_code == 204
    assert client.get("/api/v1/staff/stores", headers=staff).json()[0]["id"] == store["id"]
    assert roster(client, owner)[0]["revision"] == 3


def test_stale_and_unversioned_assignment_edits_cannot_restore_access(client):
    owner, _, store, _, person, _ = team(client)
    assert update(client, owner, person, []).status_code == 204
    assert update(client, owner, person, [store["id"]]).status_code == 409
    assert (
        client.put(
            f"/api/v1/merchant/staff/{person['id']}/assignments",
            headers=owner,
            json={"store_ids": [store["id"]]},
        ).status_code
        == 422
    )
    assert roster(client, owner)[0]["store_ids"] == []


def test_concurrent_edits_have_one_winner(client):
    owner, _, store, _, person, _ = team(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(
            pool.map(
                lambda stores: update(client, owner, person, stores).status_code,
                [[], [store["id"]]],
            )
        )
    assert sorted(codes) == [204, 409]
    assert roster(client, owner)[0]["revision"] == 2


def test_second_business_and_sessions_survive_revocation(client):
    owner, _, _, staff, person, _ = team(client)
    second, _, store = business(client)
    assert accept(client, invite(client, second, store, person["email"])).status_code == 200
    assert update(client, owner, person, []).status_code == 204
    assert roster(client, second)[0]["revision"] == 1
    assert roster(client, second)[0]["store_ids"] == [store["id"]]
    assert client.get("/api/v1/staff/stores", headers=staff).json()[0]["id"] == store["id"]
    assert client.get("/api/v1/auth/me", headers=staff).status_code == 200


@pytest.mark.parametrize("role", [Role.USER, Role.MERCHANT_STAFF, Role.ADMIN, Role.SUPER_ADMIN])
def test_staff_admin_endpoints_are_merchant_only(client, role):
    h = bearer(login(client, create_user(client, role)))
    for path in ["/merchant/staff", "/merchant/invitations", "/merchant/staff-audit"]:
        assert client.get("/api/v1" + path, headers=h).status_code == 403
    assert (
        client.post(f"/api/v1/merchant/invitations/{uuid4()}/reissue", headers=h).status_code == 403
    )
    assert update(client, h, {"id": str(uuid4())}, []).status_code == 403


def test_cross_business_reissue_and_roster_restoration_rejected(client):
    owner, _, _, _, person, invitation = team(client)
    other, _, store = business(client)
    assert (
        client.post(
            f"/api/v1/merchant/invitations/{invitation['invitation']['id']}/reissue", headers=other
        ).status_code
        == 404
    )
    assert update(client, other, person, [store["id"]]).status_code == 404
    assert client.get("/api/v1/merchant/staff-audit", headers=other).json() == []
    assert roster(client, other) == []


@pytest.mark.parametrize("state", ["PENDING", "CANCELLED", "EXPIRED"])
def test_reissue_rotates_private_token_and_rejects_old_link(client, state):
    owner, _, store = business(client)
    old = invite(client, owner, store)
    with Session(client.app.state.engine) as db:
        row = db.get(Invitation, UUID(old["invitation"]["id"]))
        if state == "CANCELLED":
            row.closed_at = datetime.now(UTC)
        if state == "EXPIRED":
            row.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    result = client.post(
        f"/api/v1/merchant/invitations/{old['invitation']['id']}/reissue", headers=owner
    )
    assert result.status_code == 201
    new = result.json()
    assert new["token"] != old["token"] and new["invitation"]["status"] == "PENDING"
    assert accept(client, old).status_code == 410
    assert accept(client, new).status_code == 200
    response = client.get("/api/v1/merchant/invitations", headers=owner)
    assert (
        old["token"] not in response.text
        and new["token"] not in response.text
        and "token_hash" not in response.text
    )
    assert (
        len(client.get("/api/v1/merchant/invitations?status=ACCEPTED", headers=owner).json()) == 1
    )


def test_accepted_invitation_cannot_be_reissued(client):
    owner, _, _, _, _, invitation = team(client)
    assert (
        client.post(
            f"/api/v1/merchant/invitations/{invitation['invitation']['id']}/reissue", headers=owner
        ).status_code
        == 409
    )


def test_inactive_staff_cannot_receive_new_access_or_invitations(client):
    owner, _, store, _, person, _ = team(client)
    with Session(client.app.state.engine) as db:
        db.get(User, UUID(person["id"])).is_active = False
        db.commit()
    assert not roster(client, owner)[0]["account_active"]
    assert update(client, owner, person, [store["id"]]).status_code == 409
    assert (
        client.post(
            "/api/v1/merchant/invitations",
            headers=owner,
            json={"email": person["email"], "store_ids": [store["id"]]},
        ).status_code
        == 409
    )
    assert update(client, owner, person, []).status_code == 204


def test_suspended_business_can_revoke_but_cannot_restore(client):
    owner, merchant, store, _, person, _ = team(client)
    with Session(client.app.state.engine) as db:
        db.get(Merchant, UUID(merchant["id"])).status = "SUSPENDED"
        db.commit()
    assert update(client, owner, person, []).status_code == 204
    assert update(client, owner, person, [store["id"]], 2).status_code == 409


def test_accepting_another_invitation_advances_edit_revision(client):
    owner, _, store, _, person, _ = team(client)
    old = roster(client, owner)[0]
    assert accept(client, invite(client, owner, store, person["email"])).status_code == 200
    assert roster(client, owner)[0]["revision"] == 2
    assert update(client, owner, person, [], old["revision"]).status_code == 409


def test_audit_shows_before_after_and_never_invitation_secrets(client):
    owner, _, store, _, person, invitation = team(client)
    assert update(client, owner, person, []).status_code == 204
    response = client.get("/api/v1/merchant/staff-audit", headers=owner)
    rows = response.json()
    assert len(rows) == 3
    change = next(r for r in rows if r["action"] == "STAFF_ASSIGNMENTS_CHANGED")
    assert (
        change["before_stores"] == [store["name"]]
        and change["stores"] == []
        and change["subject"] == person["display_name"]
    )
    assert (
        invitation["token"] not in response.text
        and "password" not in response.text
        and "token_hash" not in response.text
    )
    assert response.headers["cache-control"] == "no-store"


def test_roster_invitation_and_audit_pagination(client):
    owner, merchant, store, _, _, _ = team(client)
    with Session(client.app.state.engine) as db:
        for n in range(26):
            u = User(
                email=f"pagination-{n}@example.com",
                display_name=f"Staff {n}",
                role=Role.MERCHANT_STAFF,
                password_hash="unused",
            )
            db.add(u)
            db.flush()
            db.add(StaffAccess(merchant_id=UUID(merchant["id"]), staff_id=u.id))
            db.add(
                Invitation(
                    merchant_id=UUID(merchant["id"]),
                    email=u.email,
                    token_hash=f"pagination-{n}",
                    store_ids=[store["id"]],
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            db.add(AuditEvent(merchant_id=UUID(merchant["id"]), action="STAFF_INVITED", detail={}))
        db.commit()
    for path in ["staff", "invitations", "staff-audit"]:
        first = client.get("/api/v1/merchant/" + path, headers=owner).json()
        second = client.get("/api/v1/merchant/" + path + "?offset=25", headers=owner).json()
        assert len(first) == 25 and len(second) > 0
        assert {r["id"] for r in first}.isdisjoint({r["id"] for r in second})
        assert (
            client.get("/api/v1/merchant/" + path + "?offset=-1", headers=owner).status_code == 422
        )
    assert (
        len(client.get("/api/v1/merchant/invitations?status=PENDING", headers=owner).json()) == 25
    )
    assert (
        client.get("/api/v1/merchant/invitations?status=INVALID", headers=owner).status_code == 422
    )


def test_reissue_revalidates_closed_branch(client):
    owner, _, store = business(client)
    invitation = invite(client, owner, store)
    with Session(client.app.state.engine) as db:
        db.get(Store, UUID(store["id"])).status = "INACTIVE"
        db.commit()
    assert (
        client.post(
            f"/api/v1/merchant/invitations/{invitation['invitation']['id']}/reissue", headers=owner
        ).status_code
        == 403
    )


def test_migration_backfills_active_and_previously_revoked_staff_without_granting_access(
    client, monkeypatch
):
    from alembic.config import Config

    from alembic import command

    owner, merchant, store, _, person, _ = team(client)
    assert update(client, owner, person, []).status_code == 204
    legacy = create_user(client, Role.MERCHANT_STAFF)
    pending = create_user(client, Role.MERCHANT_STAFF)
    invite(client, owner, store, pending.email)
    with Session(client.app.state.engine) as db:
        db.add(
            StaffAssignment(
                merchant_id=UUID(merchant["id"]), staff_id=legacy.id, store_id=UUID(store["id"])
            )
        )
        db.commit()
    url = client.app.state.engine.url
    assert url.database.endswith("_test")
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    config = Config("alembic.ini")
    try:
        command.downgrade(config, "fb336b1dfdd7")
    finally:
        command.upgrade(config, "head")
    command.check(config)
    rows = {r["id"]: r for r in roster(client, owner)}
    assert set(rows) == {person["id"], str(legacy.id)}
    assert rows[person["id"]]["store_ids"] == []
    assert rows[str(legacy.id)]["store_ids"] == [store["id"]]
