from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import DB, csrf
from app.offers.models import Category, Offer
from app.offers.schemas import (
    Action,
    AdminOfferOutput,
    CategoryInput,
    CategoryOutput,
    CategoryUpdate,
    OfferInput,
    OfferOutput,
    OfferUpdate,
    Review,
)
from app.offers.service import (
    check_revision,
    effective_status,
    fail,
    output,
    record,
    require_publishable,
    schedule_expiry,
    touch,
    validate_targets,
)
from app.profiles.models import AuditEvent, Merchant, Store
from app.profiles.router import Owner, Reviewer, owned, verified

router = APIRouter(prefix="/api/v1", tags=["Offer management"], dependencies=[Depends(csrf)])
public_categories = APIRouter(prefix="/api/v1", tags=["Categories"])


@public_categories.get("/categories", response_model=list[CategoryOutput])
def categories(db: DB) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.name, Category.id)
        )
    )


@router.get("/admin/categories", response_model=list[CategoryOutput])
def admin_categories(db: DB, user: Reviewer) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.name, Category.id)))


@router.post("/admin/categories", response_model=CategoryOutput, status_code=201)
def create_category(data: CategoryInput, db: DB, user: Reviewer) -> Category:
    item = Category(**data.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("A category with this name already exists.")
    record(db, user, None, "CATEGORY_CREATED", category_id=str(item.id), name=item.name)
    db.commit()
    db.refresh(item)
    return item


@router.put("/admin/categories/{category_id}", response_model=CategoryOutput)
def update_category(category_id: UUID, data: CategoryUpdate, db: DB, user: Reviewer) -> Category:
    item = db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if item is None:
        fail("Category not found.", 404)
    if not (item is not None):
        raise RuntimeError("Required application state is unavailable")
    if item.revision != data.revision:
        fail("This category changed. Reload categories before saving.")
    for field, value in data.model_dump(exclude={"revision"}).items():
        setattr(item, field, value)
    item.revision += 1
    item.updated_at = datetime.now(UTC)
    record(
        db,
        user,
        None,
        "CATEGORY_UPDATED",
        category_id=str(item.id),
        name=item.name,
        is_active=item.is_active,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("A category with this name already exists.")
    db.refresh(item)
    return item


@router.delete("/admin/categories/{category_id}", status_code=204)
def delete_category(
    category_id: UUID, db: DB, user: Reviewer, revision: Annotated[int, Query(ge=1)]
) -> None:
    item = db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if item is None:
        fail("Category not found.", 404)
    if not (item is not None):
        raise RuntimeError("Required application state is unavailable")
    if item.revision != revision:
        fail("This category changed. Reload categories before deleting.")
    if db.scalar(select(exists().where(Offer.category_id == item.id))):
        fail("This category is used by offers. Deactivate it instead.")
    record(db, user, None, "CATEGORY_DELETED", category_id=str(item.id), name=item.name)
    db.execute(delete(Category).where(Category.id == item.id))
    db.commit()


@router.get("/merchant/offers/config")
def offer_config(user: Owner, request: Request) -> dict[str, object]:
    return {
        "moderation_enabled": request.app.state.settings.offer_moderation_enabled,
        "currency": "INR",
    }


@router.get("/merchant/offers", response_model=list[OfferOutput])
def merchant_offers(
    db: DB, user: Owner, offset: Annotated[int, Query(ge=0, le=10000)] = 0
) -> list[OfferOutput]:
    merchant = owned(db, user)
    items = db.scalars(
        select(Offer)
        .where(Offer.merchant_id == merchant.id)
        .order_by(Offer.updated_at.desc(), Offer.id)
        .offset(offset)
        .limit(25)
    )
    return [output(item) for item in items]


@router.post("/merchant/offers", response_model=OfferOutput, status_code=201)
def create_offer(data: OfferInput, db: DB, user: Owner) -> OfferOutput:
    merchant = owned(db, user)
    verified(merchant)
    validate_targets(db, merchant, data.category_id, data.store_id)
    if data.expires_at <= datetime.now(UTC):
        fail("Choose a future expiry date.", 422)
    item = Offer(merchant_id=merchant.id, **data.model_dump())
    db.add(item)
    db.flush()
    schedule_expiry(db, item)
    record(db, user, merchant.id, "OFFER_CREATED", offer_id=str(item.id))
    db.commit()
    db.refresh(item)
    return output(item)


@router.put("/merchant/offers/{offer_id}", response_model=OfferOutput)
def edit_offer(offer_id: UUID, data: OfferUpdate, db: DB, user: Owner) -> OfferOutput:
    merchant = owned(db, user)
    verified(merchant)
    item = db.scalar(
        select(Offer)
        .where(Offer.id == offer_id, Offer.merchant_id == merchant.id)
        .with_for_update()
    )
    if item is None:
        fail("Offer not found.", 404)
    if not (item is not None):
        raise RuntimeError("Required application state is unavailable")
    check_revision(item, data.revision)
    if item.status == "ARCHIVED":
        fail("Archived offers cannot be edited. Create a new draft.")
    if data.expires_at <= datetime.now(UTC):
        fail("Choose a future expiry date.", 422)
    validate_targets(db, merchant, data.category_id, data.store_id)
    previous_expiry = item.expires_at
    for field, value in data.model_dump(exclude={"revision"}).items():
        setattr(item, field, value)
    item.status, item.approved = "DRAFT", False
    # An administrative hold survives edits; only a reviewer can release it.
    if not item.admin_hold:
        item.moderation_note = ""
    touch(item)
    if previous_expiry != item.expires_at:
        schedule_expiry(db, item)
    record(db, user, merchant.id, "OFFER_EDITED", offer_id=str(item.id), revision=item.revision)
    db.commit()
    db.refresh(item)
    return output(item)


@router.post("/merchant/offers/{offer_id}/actions", response_model=OfferOutput)
def offer_action(
    offer_id: UUID, data: Action, db: DB, user: Owner, request: Request
) -> OfferOutput:
    merchant = owned(db, user)
    item = db.scalar(
        select(Offer)
        .where(Offer.id == offer_id, Offer.merchant_id == merchant.id)
        .with_for_update()
    )
    if item is None:
        fail("Offer not found.", 404)
    if not (item is not None):
        raise RuntimeError("Required application state is unavailable")
    check_revision(item, data.revision)
    state = effective_status(item)
    if data.action == "SUBMIT":
        if state not in {"DRAFT", "REJECTED", "PAUSED"}:
            fail("Only drafts, rejected, or paused offers can be submitted.")
        require_publishable(db, item, merchant)
        if item.admin_hold:
            # A hold may only be lifted by a reviewer, even if global moderation is off.
            item.status = "PENDING_APPROVAL"
        elif item.approved or not request.app.state.settings.offer_moderation_enabled:
            item.status, item.approved = "ACTIVE", True
        else:
            item.status = "PENDING_APPROVAL"
    elif data.action == "PAUSE":
        if state not in {"ACTIVE", "PENDING_APPROVAL"}:
            fail("Only active or submitted offers can be paused.")
        item.status = "PAUSED"
    else:
        if item.status == "ARCHIVED":
            fail("This offer is already archived.")
        item.status = "ARCHIVED"
    touch(item)
    record(
        db, user, merchant.id, "OFFER_" + data.action, offer_id=str(item.id), revision=item.revision
    )
    db.commit()
    db.refresh(item)
    return output(item)


@router.get("/admin/offers", response_model=list[AdminOfferOutput])
def review_queue(
    db: DB,
    user: Reviewer,
    status: Annotated[
        Literal["DRAFT", "PENDING_APPROVAL", "ACTIVE", "PAUSED", "REJECTED", "EXPIRED", "ARCHIVED"]
        | None,
        Query(),
    ] = "PENDING_APPROVAL",
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[AdminOfferOutput]:
    query = (
        select(Offer, Merchant.business_name, Category.name, Store.name)
        .join(Merchant, Merchant.id == Offer.merchant_id)
        .join(Category, Category.id == Offer.category_id)
        .outerjoin(Store, Store.id == Offer.store_id)
    )
    if status == "EXPIRED":
        query = query.where(
            or_(
                Offer.status == "EXPIRED",
                (Offer.expires_at <= func.now()) & (Offer.status != "ARCHIVED"),
            )
        )
    elif status:
        query = query.where(Offer.status == status)
        if status != "ARCHIVED":
            query = query.where(Offer.expires_at > func.now())
    rows = db.execute(query.order_by(Offer.updated_at, Offer.id).offset(offset).limit(25))
    return [
        AdminOfferOutput(
            **output(item).model_dump(),
            business_name=business,
            category_name=category,
            store_name=store,
        )
        for item, business, category, store in rows
    ]


@router.post("/admin/offers/{offer_id}/review", response_model=OfferOutput)
def review_offer(offer_id: UUID, data: Review, db: DB, user: Reviewer) -> OfferOutput:
    merchant_id = db.scalar(select(Offer.merchant_id).where(Offer.id == offer_id))
    merchant = db.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update())
    item = db.scalar(select(Offer).where(Offer.id == offer_id).with_for_update())
    if item is None or merchant is None:
        fail("Offer not found.", 404)
    if not (item is not None and merchant is not None):
        raise RuntimeError("Required application state is unavailable")
    check_revision(item, data.revision)
    state = effective_status(item)
    if data.action in {"REJECT", "SUSPEND"} and not data.note:
        fail("Provide a reason for rejection or suspension.", 422)
    if data.action == "APPROVE":
        if state != "PENDING_APPROVAL":
            fail("Only submitted offers can be approved.")
        require_publishable(db, item, merchant)
        item.status, item.approved, item.admin_hold = "ACTIVE", True, False
    elif data.action == "REJECT":
        if state != "PENDING_APPROVAL":
            fail("Only submitted offers can be rejected.")
        item.status, item.approved, item.admin_hold = "REJECTED", False, True
    elif data.action == "SUSPEND":
        if state != "ACTIVE":
            fail("Only active offers can be suspended.")
        item.status, item.admin_hold = "PAUSED", True
    else:
        if state != "PAUSED" or not item.admin_hold or not item.approved:
            fail(
                "Only a suspended, unchanged approved offer can be reactivated. "
                "Review edited offers again."
            )
        require_publishable(db, item, merchant)
        item.status, item.admin_hold = "ACTIVE", False
    item.moderation_note = data.note
    touch(item)
    record(
        db,
        user,
        merchant.id,
        "OFFER_REVIEWED",
        offer_id=str(item.id),
        decision=data.action,
        note=data.note,
        revision=item.revision,
    )
    if data.action in {"APPROVE", "REJECT"}:
        from app.jobs.service import enqueue

        enqueue(
            db,
            kind="notification.offer_reviewed",
            payload={
                "offer_id": str(item.id),
                "revision": item.revision,
                "decision": data.action,
                "title": item.title,
            },
            key=f"offer-reviewed:{item.id}:{item.revision}",
        )
    db.commit()
    db.refresh(item)
    return output(item)


@router.get("/admin/offers/{offer_id}/audit")
def offer_audit(offer_id: UUID, db: DB, user: Reviewer) -> list[dict[str, object]]:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.detail["offer_id"].astext == str(offer_id))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .limit(100)
    )
    return [
        {
            "id": item.id,
            "action": item.action,
            "actor_id": item.actor_id,
            "detail": item.detail,
            "created_at": item.created_at,
        }
        for item in events
    ]
