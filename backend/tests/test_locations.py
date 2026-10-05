from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_profiles import BUSINESS, accept, business, invite, staff_session

from app.auth.models import Role, User
from app.core.config import Settings
from app.profiles.models import AuditEvent, Merchant, StaffAssignment
from app.profiles.schemas import StoreInput

pytestmark = pytest.mark.integration


def update_store(client, owner, store, **changes):
    data = {key: store[key] for key in StoreInput.model_fields if key in store}
    return client.put(
        f"/api/v1/merchant/stores/{store['id']}",
        headers=owner,
        json={**data, "revision": store["revision"], **changes},
    )


def located(client, latitude=9.965, longitude=76.242):
    owner, merchant, store = business(client)
    response = update_store(
        client,
        owner,
        store,
        latitude=latitude,
        longitude=longitude,
        area="Fort Kochi",
        state="Kerala",
        postal_code="682001",
    )
    assert response.status_code == 200, response.text
    return owner, merchant, response.json()


def nearby(client, latitude=9.965, longitude=76.242, **params):
    return client.get(
        "/api/v1/locations/nearby", params={"latitude": latitude, "longitude": longitude, **params}
    )


def test_branch_update_preserves_identity_and_audits_revision(client):
    owner, _, store = located(client)
    updated = update_store(client, owner, store, name="Renamed branch", address="20 Harbour Road")
    assert updated.status_code == 200
    assert updated.json()["id"] == store["id"]
    assert updated.json()["revision"] == store["revision"] + 1
    assert update_store(client, owner, store, name="Stale rename").status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "STORE_UPDATED"))
        point = db.execute(
            text(
                "SELECT ST_X(location::geometry), ST_Y(location::geometry), "
                "ST_SRID(location::geometry) FROM stores WHERE id=:id"
            ),
            {"id": store["id"]},
        ).one()
        assert tuple(point) == (76.242, 9.965, 4326)


def test_store_edit_cannot_cross_owner_or_override_ownership(client):
    owner, _, store = located(client)
    other, _, _ = business(client)
    assert update_store(client, other, store, name="Stolen branch").status_code == 404
    assert update_store(client, owner, store, merchant_id=str(UUID(int=0))).status_code == 422
    for role in (Role.USER, Role.MERCHANT_STAFF, Role.ADMIN, Role.SUPER_ADMIN):
        headers = bearer(login(client, create_user(client, role)))
        assert update_store(client, headers, store).status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": 91, "longitude": 76},
        {"latitude": 9, "longitude": -181},
        {"latitude": "NaN", "longitude": 0},
        {"latitude": 9, "longitude": None},
        {"latitude": None, "longitude": 76},
        {"timezone": "Not/AZone"},
        {"country": "India"},
        {"status": "VERIFIED"},
    ],
)
def test_invalid_store_location_rejected(client, change):
    owner, _, store = business(client)
    assert update_store(client, owner, store, **change).status_code == 422


def test_nearby_uses_geography_radius_distance_order_and_pagination(client):
    owner, _, store = located(client)
    names = []
    with Session(client.app.state.engine) as db:
        for name, meters in [
            ("Inside boundary", 4999.9),
            ("Outside boundary", 5000.1),
            ("Near branch", 1000),
        ]:
            lat, lon = db.execute(
                text(
                    "SELECT ST_Y(p::geometry), ST_X(p::geometry) FROM (SELECT ST_Project("
                    "ST_SetSRID(ST_MakePoint(76.242,9.965),4326)::geography, "
                    ":meters, radians(45)) p) points"
                ),
                {"meters": meters},
            ).one()
            created = client.post(
                "/api/v1/merchant/stores",
                headers=owner,
                json={
                    "name": name,
                    "address": "Another street",
                    "city": "Kochi",
                    "latitude": lat,
                    "longitude": lon,
                },
            )
            assert created.status_code == 201
            names.append(created.json()["id"])
    response = nearby(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["radius_km"] == 5
    assert body["centre"] == {"type": "Point", "coordinates": [76.242, 9.965]}
    assert [s["name"] for s in body["stores"]] == [store["name"], "Near branch", "Inside boundary"]
    assert [s["distance_meters"] for s in body["stores"]] == [0, 1000, 4999.9]
    assert body["stores"][0]["geometry"]["coordinates"] == [76.242, 9.965]
    assert (
        "owner_id" not in response.text
        and "password" not in response.text
        and "review_note" not in response.text
    )
    assert len(nearby(client, radius_km=10).json()["stores"]) == 4
    assert nearby(client, radius_km=10.1).status_code == 422
    pages, offset = [], 0
    while offset is not None:
        page = nearby(client, limit=1, offset=offset).json()
        pages += [s["id"] for s in page["stores"]]
        offset = page["next_offset"]
    assert len(pages) == len(set(pages)) == 3
    assert body["next_offset"] is None


@pytest.mark.parametrize(
    "latitude,longitude,other_lat,other_lon",
    [(0, 179.99, 0, -179.99), (89.99, 90, 89.99, -90), (0, 0, 0, 0)],
)
def test_dateline_poles_and_zero_coordinates(client, latitude, longitude, other_lat, other_lon):
    owner, _, store = located(client, latitude, longitude)
    assert (
        client.post(
            "/api/v1/merchant/stores",
            headers=owner,
            json={
                "name": "Second point",
                "address": "A physical address",
                "city": "Test city",
                "latitude": other_lat,
                "longitude": other_lon,
            },
        ).status_code
        == 201
    )
    result = nearby(client, latitude, longitude).json()
    assert len(result["stores"]) == 2
    assert all(s["distance_meters"] < 5000 for s in result["stores"])
    if latitude == 0 and longitude == 0:
        ids = [s["id"] for s in result["stores"]]
        assert ids == sorted(ids)


def test_discovery_visibility_requires_coordinates_active_verified_owner(client):
    owner, merchant, store = business(client)
    assert nearby(client).json()["stores"] == []
    store = update_store(client, owner, store, latitude=9.965, longitude=76.242).json()
    detail = f"/api/v1/locations/stores/{store['id']}"
    assert client.get(detail).status_code == 200
    store = update_store(client, owner, store, status="INACTIVE").json()
    assert nearby(client).json()["stores"] == [] and client.get(detail).status_code == 404
    store = update_store(client, owner, store, status="ACTIVE").json()
    with Session(client.app.state.engine) as db:
        row = db.get(Merchant, UUID(merchant["id"]))
        row.status = "SUSPENDED"
        db.commit()
    assert nearby(client).json()["stores"] == [] and client.get(detail).status_code == 404
    with Session(client.app.state.engine) as db:
        row = db.get(Merchant, UUID(merchant["id"]))
        row.status = "VERIFIED"
        db.get(User, row.owner_id).is_active = False
        db.commit()
    assert nearby(client).json()["stores"] == []


def test_coordinate_edits_move_store_and_missing_coordinates_hide_it(client):
    owner, _, store = located(client)
    assert len(nearby(client).json()["stores"]) == 1
    store = update_store(client, owner, store, longitude=77).json()
    assert nearby(client).json()["stores"] == []
    assert len(nearby(client, longitude=77).json()["stores"]) == 1
    update_store(client, owner, store, latitude=None, longitude=None)
    assert nearby(client, longitude=77).json()["stores"] == []


def test_manual_places_are_public_unambiguous_and_only_visible_stores(client):
    owner, _, store = located(client)
    cities = client.get("/api/v1/locations/cities?q=ko").json()
    assert cities == [{"country": "IN", "state": "Kerala", "city": "Kochi"}]
    areas = client.get("/api/v1/locations/areas?city=kochi&state=Kerala&country=IN").json()
    assert areas[0]["area"] == "Fort Kochi"
    places = client.get("/api/v1/locations/places?q=fort").json()
    assert places[0]["id"] == store["id"] and places[0]["latitude"] == 9.965
    assert places[0]["reference_name"] == store["name"]
    assert client.get("/api/v1/locations/places?q=%25%25").json() == []
    assert client.get("/api/v1/locations/places?q=%20%20").status_code == 422
    assert client.get("/api/v1/locations/places?q=unknown-place").json() == []
    update_store(client, owner, store, status="INACTIVE")
    assert client.get("/api/v1/locations/cities").json() == []
    assert client.get("/api/v1/locations/places?q=fort").json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"latitude": "NaN", "longitude": 0},
        {"latitude": 9},
        {"latitude": 90.1, "longitude": 0},
        {"latitude": 0, "longitude": "Infinity"},
        {"latitude": 0, "longitude": 0, "offset": -1},
        {"latitude": 0, "longitude": 0, "limit": 1000},
        {"latitude": 0, "longitude": 0, "radius_km": 0},
        {"latitude": 0, "longitude": 0, "radius_km": "NaN"},
    ],
)
def test_invalid_discovery_queries_rejected(client, params):
    assert client.get("/api/v1/locations/nearby", params=params).status_code == 422


def test_inactive_store_blocks_staff_and_pending_invites_preserves_assignment(client):
    owner, _, store = located(client)
    staff, _ = staff_session(client, invite(client, owner, store))
    pending = invite(client, owner, store)
    store = update_store(client, owner, store, status="INACTIVE").json()
    assert client.get("/api/v1/staff/stores", headers=staff).json() == []
    assert client.get(f"/api/v1/staff/stores/{store['id']}", headers=staff).status_code == 403
    assert accept(client, pending).status_code == 403
    assert (
        client.post(
            "/api/v1/merchant/invitations",
            headers=owner,
            json={"email": "new@example.com", "store_ids": [store["id"]]},
        ).status_code
        == 403
    )
    with Session(client.app.state.engine) as db:
        assert len(list(db.scalars(select(StaffAssignment)))) == 1
    update_store(client, owner, store, status="ACTIVE")
    assert client.get(f"/api/v1/staff/stores/{store['id']}", headers=staff).status_code == 200


def test_hours_save_and_public_details_without_contact_account_leaks(client):
    owner, _, store = located(client)
    hours = [{"day_of_week": day, "is_closed": True} for day in range(7)]
    result = update_store(client, owner, store, hours=hours)
    assert result.status_code == 200
    response = client.get(f"/api/v1/locations/stores/{store['id']}")
    assert len(response.json()["hours"]) == 7
    assert response.json()["is_open"] is False
    assert len(nearby(client).json()["stores"]) == 1  # Closed now is different from inactive.
    assert BUSINESS["contact_email"] not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_concurrent_branch_edits_cannot_overwrite_each_other(client):
    owner, _, store = located(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(
            pool.map(
                lambda i: update_store(client, owner, store, name=f"Branch {i}").status_code,
                range(2),
            )
        ) == [200, 409]


def test_database_coordinate_constraints_and_spatial_index(client):
    _, _, store = located(client)
    with Session(client.app.state.engine) as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE stores SET latitude=91 WHERE id=:id"), {"id": store["id"]})
        db.rollback()
        db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = db.execute(
            text(
                "EXPLAIN SELECT id FROM stores WHERE ST_DWithin(location, "
                "ST_SetSRID(ST_MakePoint(76.242,9.965),4326)::geography, 5000)"
            )
        ).all()
        assert "ix_stores_location" in str(plan)
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE conrelid='stores'::regclass "
                    "AND conname IN ('store_status','store_coordinate_pair',"
                    "'store_coordinate_bounds')"
                )
            ).scalar_one()
            == 3
        )


def test_config_radius_limits_are_consistent(client):
    assert client.get("/api/v1/locations/config").json() == {
        "default_radius_km": 5,
        "max_radius_km": 10,
    }
    with pytest.raises(ValidationError):
        Settings(discovery_radius_km=10, discovery_max_radius_km=5)


def test_store_validation_messages_are_contextual_and_do_not_echo_input(client):
    owner, _, store = located(client)
    response = update_store(client, owner, store, timezone="private-invalid-timezone")
    assert response.status_code == 422
    assert "timezone" in response.json()["error"]["message"]
    assert "private-invalid-timezone" not in response.text
    assert "Passwords" not in response.text
