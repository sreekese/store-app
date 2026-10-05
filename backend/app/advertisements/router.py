from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select, text

from app.advertisements.models import Advertisement
from app.advertisements.schemas import Action, AdInput, AdUpdate, Revision, Status
from app.advertisements.service import (
    card,
    conflicts,
    eligible,
    fail,
    offer_candidates,
    output,
    validate_target,
)
from app.auth.dependencies import DB, csrf, require_roles
from app.auth.models import Role, User
from app.locations.router import visible
from app.offers.models import Offer
from app.offers.service import record
from app.profiles.models import AuditEvent, Merchant, Store

router = APIRouter(
    prefix="/api/v1/advertisements", tags=["Advertisements"], dependencies=[Depends(csrf)]
)
Super = Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]
Offset = Annotated[int, Query(ge=0, le=10000)]


def get_ad(db: DB, id: UUID, revision: int | None = None) -> Advertisement:
    row = db.scalar(select(Advertisement).where(Advertisement.id == id).with_for_update())
    if row is None:
        fail("Advertisement not found.", 404)
    if revision is not None and row.revision != revision:
        fail("This advertisement changed. Refresh it before continuing.")
    return row


def audit(db: DB, user: User, row: Advertisement, action: str) -> None:
    data = output(row)
    # Store a complete versioned configuration, never the temporary preview token.
    snapshot = {k: str(v) if isinstance(v, (UUID, datetime)) else v for k, v in data.items()}
    record(db, user, None, "AD_" + action, advertisement_id=str(row.id), snapshot=snapshot)


@router.get("")
def public(db: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(Advertisement)
        .where(
            Advertisement.status == "ENABLED",
            Advertisement.starts_at <= now,
            Advertisement.expires_at > now,
        )
        .order_by(Advertisement.placement, Advertisement.id)
    )
    items = []
    for row in rows:
        if eligible(db, row):
            item = card(row)
            if row.offer_id:
                offer = db.get(Offer, row.offer_id)
                if offer:
                    item["valid_until"] = min(row.expires_at, offer.expires_at)
            items.append(item)
    return {"server_time": now, "items": items}


@router.get("/manage")
def listing(
    db: DB, user: Super, offset: Offset = 0, status: Status | None = None
) -> dict[str, Any]:
    query = select(Advertisement)
    if status:
        query = query.where(Advertisement.status == status)
    rows = list(
        db.scalars(
            query.order_by(Advertisement.updated_at.desc(), Advertisement.id)
            .offset(offset)
            .limit(21)
        )
    )
    return {
        "items": [output(r) for r in rows[:20]],
        "next_offset": offset + 20 if len(rows) > 20 and offset + 20 <= 10000 else None,
    }


@router.get("/destinations/stores")
def stores(
    db: DB, user: Super, q: str = Query("", max_length=100), offset: Offset = 0
) -> list[dict[str, Any]]:
    query = visible()
    if q:
        query = query.where(
            or_(
                Store.name.icontains(q, autoescape=True),
                Store.city.icontains(q, autoescape=True),
                Merchant.business_name.icontains(q, autoescape=True),
            )
        )
    return [
        {"id": s.id, "label": f"{m.business_name} · {s.name}, {s.city}"}
        for s, m in db.execute(query.order_by(Store.name, Store.id).offset(offset).limit(25))
    ]


@router.get("/destinations/offers")
def offers(db: DB, user: Super, store_id: UUID, offset: Offset = 0) -> list[dict[str, Any]]:
    return [
        {"id": o.id, "label": o.title, "starts_at": o.starts_at, "expires_at": o.expires_at}
        for o in db.scalars(
            offer_candidates(store_id)
            .with_only_columns(Offer)
            .order_by(Offer.title, Offer.id)
            .offset(offset)
            .limit(25)
        )
    ]


@router.post("/manage", status_code=201)
def create(data: AdInput, db: DB, user: Super) -> dict[str, Any]:
    validate_target(db, data)
    row = Advertisement(**data.model_dump())
    db.add(row)
    db.flush()
    audit(db, user, row, "CREATED")
    db.commit()
    return output(row)


@router.get("/manage/{id}")
def detail(id: UUID, db: DB, user: Super) -> dict[str, Any]:
    return output(get_ad(db, id))


@router.put("/manage/{id}")
def update(id: UUID, data: AdUpdate, db: DB, user: Super) -> dict[str, Any]:
    row = get_ad(db, id, data.revision)
    if row.status == "ARCHIVED":
        fail("Archived advertisements cannot be edited.")
    validate_target(db, data)
    for key, value in data.model_dump(exclude={"revision"}).items():
        setattr(row, key, value)
    row.status = "DRAFT"
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    audit(db, user, row, "EDITED")
    db.commit()
    return output(row)


@router.post("/manage/{id}/preview")
def preview(id: UUID, data: Revision, db: DB, user: Super, request: Request) -> dict[str, Any]:
    row = get_ad(db, id, data.revision)
    now = datetime.now(UTC)
    proof = jwt.encode(
        {
            "sub": str(user.id),
            "advertisement_id": str(row.id),
            "revision": row.revision,
            "iss": "nearperk",
            "aud": "advertisement-preview",
            "exp": now + timedelta(minutes=10),
        },
        request.app.state.settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    audit(db, user, row, "PREVIEWED")
    result = {
        "card": card(row),
        "destination_available_now": eligible(db, row),
        "overlap": conflicts(db, row),
        "preview_token": proof,
        "preview_expires_at": now + timedelta(minutes=10),
    }
    db.commit()
    return result


@router.post("/manage/{id}/actions")
def action(id: UUID, data: Action, db: DB, user: Super, request: Request) -> dict[str, Any]:
    row = get_ad(db, id, data.revision)
    if row.status == "ARCHIVED":
        fail("Archived advertisements cannot be changed.")
    if data.action == "ENABLE":
        if row.status == "ENABLED":
            fail("This advertisement is already enabled.")
        try:
            proof = jwt.decode(
                data.preview_token,
                request.app.state.settings.jwt_secret_key.get_secret_value(),
                algorithms=["HS256"],
                issuer="nearperk",
                audience="advertisement-preview",
                options={"require": ["sub", "advertisement_id", "revision", "exp", "iss", "aud"]},
            )
            if (
                proof["sub"] != str(user.id)
                or proof["advertisement_id"] != str(row.id)
                or proof["revision"] != row.revision
            ):
                raise jwt.InvalidTokenError("Preview mismatch")
        except jwt.InvalidTokenError:
            fail("Preview this saved revision again before enabling it.")
        validate_target(db, AdInput.model_validate(output(row), extra="ignore"))
        # Serialize publication per placement, including separate ads/admin sessions.
        db.execute(
            text("SELECT pg_advisory_xact_lock(130013, :slot)"),
            {"slot": 1 if row.placement == "BELOW_DAILY" else 2},
        )
        if conflicts(db, row):
            fail(
                "Another enabled advertisement overlaps this placement and schedule. "
                "Disable it or change the dates."
            )
        row.status = "ENABLED"
    elif data.action == "DISABLE":
        if row.status != "ENABLED":
            fail("Only enabled advertisements can be disabled.")
        row.status = "DISABLED"
    else:
        row.status = "ARCHIVED"
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    audit(db, user, row, row.status)
    db.commit()
    return output(row)


@router.get("/manage/{id}/history")
def history(id: UUID, db: DB, user: Super, offset: Offset = 0) -> dict[str, Any]:
    get_ad(db, id)
    rows = list(
        db.execute(
            select(AuditEvent, User.display_name)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .where(
                AuditEvent.action.like("AD_%"),
                AuditEvent.detail["advertisement_id"].astext == str(id),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset(offset)
            .limit(21)
        )
    )
    return {
        "items": [
            {
                "id": r.id,
                "action": r.action,
                "actor": name or "Former administrator",
                "actor_id": r.actor_id,
                "created_at": r.created_at,
                "snapshot": r.detail.get("snapshot"),
            }
            for r, name in rows[:20]
        ],
        "next_offset": offset + 20 if len(rows) > 20 and offset + 20 <= 10000 else None,
    }
