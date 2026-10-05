from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select, text

from app.auth.dependencies import DB, csrf, require_roles
from app.auth.models import Role, User
from app.auth.service import AuthError
from app.coupons.models import Campaign, CampaignBranch
from app.daily.models import CouponPolicy, DailyPick
from app.daily.policy import Rules, Schedule, active, window
from app.offers.models import Category, Offer
from app.offers.service import record
from app.profiles.models import AuditEvent, Merchant, Store

router = APIRouter(prefix="/api/v1/daily", tags=["Daily coupons"], dependencies=[Depends(csrf)])
Super = Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]
Editor = Annotated[User, Depends(require_roles(Role.MERCHANT, Role.SUPER_ADMIN))]


def deny(message: str, status: int = 409) -> None:
    raise AuthError("DAILY_REQUEST_DENIED", message, status)


def policy_output(row: CouponPolicy) -> dict[str, Any]:
    return {"version": row.version, "effective_at": row.effective_at, **row.rules}


@router.get("/policy")
def read_policy(db: DB) -> dict[str, Any]:
    now = datetime.now(UTC)
    current = active(db, now)
    return {**policy_output(current), "next_reset": window(current, now)[1]}


def preview_data(db: DB, data: Schedule) -> dict[str, Any]:
    now = datetime.now(UTC)
    current = active(db, now)
    if current.version != data.current_version:
        deny("Policy changed. Refresh and preview again.")
    if (
        data.effective_at <= now
        or window(current, data.effective_at - timedelta(microseconds=1))[1] != data.effective_at
    ):
        deny("Choose a future reset boundary of the current policy.", 422)
    pending = db.scalar(select(CouponPolicy.version).where(CouponPolicy.effective_at > now))
    return {
        "current_version": current.version,
        "effective_at": data.effective_at,
        "next_reset": window(current, now)[1],
        "pending_version": pending,
        "affected_users": db.scalar(
            select(func.count()).select_from(User).where(User.role == Role.USER, User.is_active)
        )
        or 0,
        "message": (
            "Existing claims keep their terms and expiry. No allowance resets before activation."
        ),
        "rules": Rules.model_validate(
            data.model_dump(include=set(Rules.model_fields))
        ).model_dump(),
    }


@router.post("/policy/preview")
def preview(data: Schedule, db: DB, actor: Super) -> dict[str, Any]:
    return preview_data(db, data)


@router.post("/policy/schedule")
def schedule(data: Schedule, db: DB, actor: Super) -> dict[str, Any]:
    db.execute(text("SELECT pg_advisory_xact_lock(913001)"))
    result = preview_data(db, data)
    if result["pending_version"]:
        deny("Cancel the pending policy before scheduling another.")
    row = CouponPolicy(effective_at=data.effective_at, rules=result["rules"], actor_id=actor.id)
    db.add(row)
    db.flush()
    record(
        db,
        actor,
        None,
        "POLICY_SCHEDULED",
        version=row.version,
        effective_at=data.effective_at.isoformat(),
        rules=row.rules,
    )
    db.commit()
    return policy_output(row)


@router.delete("/policy/{version}")
def cancel_policy(version: int, db: DB, actor: Super) -> dict[str, bool]:
    db.execute(text("SELECT pg_advisory_xact_lock(913001)"))
    row = db.get(CouponPolicy, version)
    if row is None or row.effective_at <= datetime.now(UTC):
        deny("Only a pending policy can be cancelled.")
    if not (row is not None):
        raise RuntimeError("Required application state is unavailable")
    record(db, actor, None, "POLICY_CANCELLED", version=version, rules=row.rules)
    db.delete(row)
    db.commit()
    return {"cancelled": True}


@router.get("/policy/history")
def policy_history(db: DB, actor: Super, offset: int = Query(0, ge=0, le=10000)) -> dict[str, Any]:
    rows = db.scalars(
        select(CouponPolicy).order_by(CouponPolicy.effective_at.desc()).offset(offset).limit(25)
    )
    audit = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.action.in_(["POLICY_SCHEDULED", "POLICY_CANCELLED"]))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .offset(offset)
        .limit(25)
    )
    return {
        "policies": [policy_output(r) for r in rows],
        "audit": [
            {
                "id": a.id,
                "action": a.action,
                "at": a.created_at,
                "actor_id": a.actor_id,
                "detail": a.detail,
            }
            for a in audit
        ],
    }


def own_store(db: DB, actor: User, store_id: UUID) -> Store:
    store = db.get(Store, store_id)
    if store is None:
        deny("Branch not found.", 404)
    if not (store is not None):
        raise RuntimeError("Required application state is unavailable")
    merchant = db.scalar(select(Merchant).where(Merchant.id == store.merchant_id).with_for_update())
    if actor.role != Role.SUPER_ADMIN and (merchant is None or merchant.owner_id != actor.id):
        deny("You do not manage this branch.", 403)
    return store


def candidates_query(start: datetime, end: datetime) -> Select[tuple[Campaign, Offer, Store]]:
    return (
        select(Campaign, Offer, Store)
        .join(Offer, Offer.id == Campaign.offer_id)
        .join(CampaignBranch, CampaignBranch.campaign_id == Campaign.id)
        .join(Store, Store.id == CampaignBranch.store_id)
        .join(Merchant, Merchant.id == Store.merchant_id)
        .join(User, User.id == Merchant.owner_id)
        .join(Category, Category.id == Offer.category_id)
        .where(
            Store.status == "ACTIVE",
            Store.latitude.is_not(None),
            Merchant.status == "VERIFIED",
            User.is_active,
            Store.merchant_id == Offer.merchant_id,
            (Offer.store_id.is_(None) | (Offer.store_id == Store.id)),
            Category.is_active,
            Offer.status == "ACTIVE",
            Offer.approved,
            ~Offer.admin_hold,
            Offer.starts_at < end,
            Offer.expires_at > start,
            Campaign.status == "ACTIVE",
            Campaign.starts_at < end,
            Campaign.expires_at > start,
            Campaign.starts_at < Offer.expires_at,
            Offer.starts_at < Campaign.expires_at,
            Campaign.claimed_count < Campaign.total_quantity,
        )
    )


def dates(db: DB, day: date) -> tuple[datetime, datetime]:
    policy = active(db, datetime.now(UTC))
    zone = ZoneInfo(policy.rules["timezone"])
    today = datetime.now(zone).date()
    if day > today + timedelta(days=366):
        deny("Choose a date within the next year.", 422)
    start = datetime.combine(day, datetime.min.time(), zone)
    return start, start + timedelta(days=1)


@router.get("/stores")
def stores(
    db: DB,
    actor: Editor,
    offset: int = Query(0, ge=0, le=10000),
    q: str = Query("", max_length=100),
) -> list[dict[str, Any]]:
    query = select(Store).join(Merchant).where(Store.name.icontains(q, autoescape=True))
    if actor.role == Role.MERCHANT:
        query = query.where(Merchant.owner_id == actor.id)
    return [
        {"id": s.id, "name": s.name}
        for s in db.scalars(query.order_by(Store.name, Store.id).offset(offset).limit(25))
    ]


@router.get("/stores/{store_id}/candidates")
def candidates(
    store_id: UUID,
    business_date: date,
    db: DB,
    actor: Editor,
    offset: int = Query(0, ge=0, le=10000),
) -> list[dict[str, Any]]:
    own_store(db, actor, store_id)
    start, end = dates(db, business_date)
    return [
        {"id": c.id, "title": o.title, "available": c.total_quantity - c.claimed_count}
        for c, o, s in db.execute(
            candidates_query(start, end)
            .where(Store.id == store_id)
            .order_by(Campaign.id)
            .offset(offset)
            .limit(25)
        )
    ]


class PickInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: UUID | None
    revision: int = Field(ge=0)


@router.get("/stores/{store_id}/picks/{business_date}")
def read_pick(store_id: UUID, business_date: date, db: DB, actor: Editor) -> dict[str, Any]:
    own_store(db, actor, store_id)
    rows = list(
        db.scalars(
            select(DailyPick).where(
                DailyPick.store_id == store_id, DailyPick.business_date == business_date
            )
        )
    )
    return {
        r.source: {
            "campaign_id": r.campaign_id,
            "revision": r.revision,
            "actor_id": r.actor_id,
            "updated_at": r.updated_at,
        }
        for r in rows
    }


@router.put("/stores/{store_id}/picks/{business_date}")
def save_pick(
    store_id: UUID, business_date: date, data: PickInput, db: DB, actor: Editor
) -> dict[str, Any]:
    store = own_store(db, actor, store_id)
    start, end = dates(db, business_date)
    if end <= datetime.now(UTC):
        deny("Past business dates cannot be changed.", 422)
    source = "SUPER_ADMIN" if actor.role == Role.SUPER_ADMIN else "MERCHANT"
    row = db.get(DailyPick, (store_id, business_date, source))
    if (row.revision if row else 0) != data.revision:
        deny("Selection changed. Refresh before saving.")
    if (
        data.campaign_id is not None
        and db.execute(
            candidates_query(start, end).where(
                Store.id == store_id, Campaign.id == data.campaign_id
            )
        ).first()
        is None
    ):
        deny("Choose an eligible campaign for this branch and business date.", 422)
    if row is None:
        row = DailyPick(
            store_id=store_id,
            business_date=business_date,
            source=source,
            updated_at=datetime.now(UTC),
        )
        db.add(row)
    row.campaign_id = data.campaign_id
    row.actor_id = actor.id
    row.updated_at = datetime.now(UTC)
    row.revision = data.revision + 1
    record(
        db,
        actor,
        store.merchant_id,
        "DAILY_PICK_SAVED",
        store_id=str(store_id),
        business_date=str(business_date),
        source=source,
        campaign_id=str(data.campaign_id) if data.campaign_id else None,
    )
    db.commit()
    return {"revision": row.revision}


@router.delete("/stores/{store_id}/picks/{business_date}")
def remove_pick(
    store_id: UUID, business_date: date, revision: int, db: DB, actor: Editor
) -> dict[str, bool]:
    store = own_store(db, actor, store_id)
    source = "SUPER_ADMIN" if actor.role == Role.SUPER_ADMIN else "MERCHANT"
    row = db.get(DailyPick, (store_id, business_date, source))
    if row is None or row.revision != revision:
        deny("Selection changed. Refresh before removing.")
    if not (row is not None):
        raise RuntimeError("Required application state is unavailable")
    record(
        db,
        actor,
        store.merchant_id,
        "DAILY_PICK_REMOVED",
        store_id=str(store_id),
        business_date=str(business_date),
        source=source,
    )
    db.delete(row)
    db.commit()
    return {"removed": True}


@router.get("/stores/{store_id}/history")
def pick_history(
    store_id: UUID, db: DB, actor: Editor, offset: int = Query(0, ge=0, le=10000)
) -> list[dict[str, Any]]:
    store = own_store(db, actor, store_id)
    return [
        {
            "id": r.id,
            "action": r.action,
            "at": r.created_at,
            "actor_id": r.actor_id,
            "detail": r.detail,
        }
        for r in db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.merchant_id == store.merchant_id,
                AuditEvent.action.in_(["DAILY_PICK_SAVED", "DAILY_PICK_REMOVED"]),
                AuditEvent.detail["store_id"].astext == str(store_id),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset(offset)
            .limit(25)
        )
    ]
