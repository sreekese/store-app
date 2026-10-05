from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_offers import fixture_offer

from app.advertisements.models import Advertisement
from app.advertisements.schemas import AdInput
from app.auth.models import Role
from app.profiles.models import Store

pytestmark = pytest.mark.integration
BASE = "/api/v1/advertisements"


def admin(client):
    return bearer(login(client, create_user(client, Role.SUPER_ADMIN)))


def fields(**changes):
    return (
        dict(
            sponsor="Local sponsor",
            headline="Discover local deals",
            body="Visit nearby shops",
            cta="Explore",
            placement="BELOW_OFFERS",
            destination_type="DISCOVER",
            starts_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
        | changes
    )


def create(client, headers, **changes):
    response = client.post(BASE + "/manage", headers=headers, json=fields(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def preview(client, headers, ad):
    response = client.post(
        f"{BASE}/manage/{ad['id']}/preview", headers=headers, json={"revision": ad["revision"]}
    )
    assert response.status_code == 200, response.text
    return response.json()["preview_token"]


def act(client, headers, ad, action="ENABLE", token=""):
    return client.post(
        f"{BASE}/manage/{ad['id']}/actions",
        headers=headers,
        json={"revision": ad["revision"], "action": action, "preview_token": token},
    )


def test_lifecycle_preview_revision_audit_and_archive(client):
    headers = admin(client)
    ad = create(client, headers)
    assert client.get(BASE).json()["items"] == []
    assert act(client, headers, ad).status_code == 409
    proof = preview(client, headers, ad)
    result = act(client, headers, ad, token=proof)
    assert result.status_code == 200, result.text
    enabled = result.json()
    public = client.get(BASE).json()["items"]
    assert len(public) == 1 and public[0]["href"] == "/#discover"
    assert "revision" not in public[0] and "status" not in public[0]
    assert act(client, headers, ad, "DISABLE").status_code == 409
    data = {key: enabled[key] for key in AdInput.model_fields}
    response = client.put(
        f"{BASE}/manage/{ad['id']}",
        headers=headers,
        json={**data, "headline": "Updated headline", "revision": enabled["revision"]},
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["status"] == "DRAFT" and client.get(BASE).json()["items"] == []
    assert act(client, headers, edited, token=proof).status_code == 409
    archived = act(client, headers, edited, "ARCHIVE").json()
    assert (
        act(client, headers, archived, token=preview(client, headers, archived)).status_code == 409
    )
    history = client.get(f"{BASE}/manage/{ad['id']}/history", headers=headers).json()["items"]
    assert {r["action"] for r in history} >= {
        "AD_CREATED",
        "AD_PREVIEWED",
        "AD_ENABLED",
        "AD_EDITED",
        "AD_ARCHIVED",
    }
    assert all("preview_token" not in r["snapshot"] for r in history)


@pytest.mark.parametrize("role", [Role.USER, Role.ADMIN, Role.MERCHANT, Role.MERCHANT_STAFF])
def test_management_is_superadmin_only(client, role):
    headers = bearer(login(client, create_user(client, role)))
    for path in [
        "/manage",
        "/destinations/stores",
        f"/destinations/offers?store_id={uuid4()}",
        f"/manage/{uuid4()}/history",
    ]:
        assert client.get(BASE + path, headers=headers).status_code == 403
    assert client.post(BASE + "/manage", headers=headers, json=fields()).status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"image_url": "http://example.com/a.png", "image_alt": "Creative"},
        {"image_url": "https://example.com/a.png"},
        {"image_url": "javascript:alert(1)", "image_alt": "Creative"},
        {"destination_type": "STORE"},
        {"store_id": str(uuid4())},
        {"starts_at": "2026-01-01T00:00:00"},
        {"placement": "HEADER"},
    ],
)
def test_invalid_configuration(client, changes):
    assert (
        client.post(
            BASE + "/manage", headers=admin(client), json={**fields(), **changes}
        ).status_code
        == 422
    )


def test_preview_is_bound_to_actor_and_ad(client):
    first = admin(client)
    second = admin(client)
    ad = create(client, first)
    other = create(client, first)
    proof = preview(client, first, ad)
    assert act(client, second, ad, token=proof).status_code == 409
    assert act(client, first, other, token=proof).status_code == 409
    assert act(client, first, ad, token=proof + "bad").status_code == 409


def test_concurrent_overlaps_and_independent_placements(client):
    headers = admin(client)
    ads = [create(client, headers), create(client, headers)]
    tokens = [preview(client, headers, ad) for ad in ads]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: act(client, headers, pair[0], token=pair[1]),
                zip(ads, tokens, strict=True),
            )
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    daily = client.post(
        BASE + "/manage", headers=headers, json={**fields(), "placement": "BELOW_DAILY"}
    ).json()
    assert act(client, headers, daily, token=preview(client, headers, daily)).status_code == 200
    assert len(client.get(BASE).json()["items"]) == 2


def test_scheduling_expiry_and_disable(client):
    headers = admin(client)
    ad = create(client, headers)
    enabled = act(client, headers, ad, token=preview(client, headers, ad)).json()
    with Session(client.app.state.engine) as db:
        row = db.get(Advertisement, UUID(ad["id"]))
        row.starts_at = datetime.now(UTC) + timedelta(minutes=1)
        db.commit()
    assert client.get(BASE).json()["items"] == []
    with Session(client.app.state.engine) as db:
        row = db.get(Advertisement, UUID(ad["id"]))
        row.starts_at = datetime.now(UTC) - timedelta(hours=2)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get(BASE).json()["items"] == []
    assert act(client, headers, enabled, "DISABLE").status_code == 200


def test_store_offer_destinations_hide_when_branch_unavailable(client):
    _, _, _, store, _, offer = fixture_offer(client)
    headers = admin(client)
    ad = create(
        client, headers, destination_type="OFFER", store_id=store["id"], offer_id=offer["id"]
    )
    assert act(client, headers, ad, token=preview(client, headers, ad)).status_code == 200
    assert (
        client.get(BASE).json()["items"][0]["href"]
        == f"/offers/{offer['id']}?store_id={store['id']}"
    )
    assert (
        client.get(
            BASE + "/destinations/offers", headers=headers, params={"store_id": store["id"]}
        ).json()[0]["id"]
        == offer["id"]
    )
    with Session(client.app.state.engine) as db:
        branch = db.get(Store, UUID(store["id"]))
        branch.status = "INACTIVE"
        db.commit()
    assert client.get(BASE).json()["items"] == []
    assert client.get(BASE + "/destinations/stores", headers=headers).json() == []


def test_adjacent_schedules_and_list_pagination(client):
    headers = admin(client)
    first = create(client, headers)
    assert act(client, headers, first, token=preview(client, headers, first)).status_code == 200
    second = create(
        client,
        headers,
        starts_at=first["expires_at"],
        expires_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    )
    assert act(client, headers, second, token=preview(client, headers, second)).status_code == 200
    assert len(client.get(BASE).json()["items"]) == 1
    for _ in range(19):
        create(client, headers)
    page = client.get(BASE + "/manage", headers=headers).json()
    assert len(page["items"]) == 20 and page["next_offset"] == 20
    assert len(client.get(BASE + "/manage?offset=20", headers=headers).json()["items"]) == 1
    assert len(client.get(BASE + "/manage?status=ENABLED", headers=headers).json()["items"]) == 2


def test_store_destination_and_offer_branch_filter(client):
    _, _, _, store, _, offer = fixture_offer(client)
    headers = admin(client)
    ad = create(client, headers, destination_type="STORE", store_id=store["id"])
    assert act(client, headers, ad, token=preview(client, headers, ad)).status_code == 200
    assert client.get(BASE).json()["items"][0]["href"] == f"/stores/{store['id']}"
    response = client.get("/api/v1/offers", params={"store_id": store["id"]})
    assert response.status_code == 200
    assert offer["id"] in response.text
    assert offer["id"] not in client.get("/api/v1/offers", params={"store_id": str(uuid4())}).text
