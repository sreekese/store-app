from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import DB, csrf, require_roles, throttle
from app.auth.models import Role, User
from app.jobs.service import enqueue
from app.offers.service import record
from app.redemptions.models import Redemption
from app.redemptions.schemas import Preview, Receipt, RedeemInput, ValidateInput
from app.redemptions.service import (
    access,
    calculate,
    check_claim,
    confirmation,
    fail,
    fingerprint,
    locked_claim,
    receipt,
    verify,
)

Actor = Annotated[User, Depends(require_roles(Role.MERCHANT, Role.MERCHANT_STAFF))]
router = APIRouter(
    prefix="/api/v1/redemptions", tags=["Coupon redemption"], dependencies=[Depends(csrf)]
)


@router.post("/validate", response_model=Preview)
def validate(data: ValidateInput, db: DB, actor: Actor, request: Request) -> Preview:
    throttle(
        request, db, "redemption", str(actor.id), request.app.state.settings.redemption_rate_limit
    )
    claim, merchant, store = locked_claim(db, actor, data)
    now = datetime.now(UTC)
    offer = check_claim(claim, store, now)
    discount = calculate(offer, data.purchase_amount, data.reward_value)
    proof, expiry = confirmation(request.app.state.settings, actor, data, claim, now)
    return Preview(
        claim_id=claim.id,
        title=offer.title,
        business_name=claim.snapshot["business_name"],
        store_name=store.name,
        expires_at=claim.expires_at,
        offer=offer,
        purchase_amount=data.purchase_amount,
        discount_amount=discount,
        payable_amount=data.purchase_amount - discount,
        confirmation_token=proof,
        confirm_before=expiry,
    )


@router.post("", response_model=Receipt)
def redeem(
    data: RedeemInput,
    db: DB,
    actor: Actor,
    request: Request,
    idempotency_key: Annotated[UUID, Header()],
) -> Receipt:
    throttle(
        request, db, "redemption", str(actor.id), request.app.state.settings.redemption_rate_limit
    )
    access(db, actor, data.store_id)
    existing = db.scalar(
        select(Redemption).where(
            Redemption.actor_id == actor.id, Redemption.idempotency_key == idempotency_key
        )
    )
    if existing:
        if existing.request_hash != fingerprint(data):
            fail("This request key was already used for different redemption details.")
        return receipt(existing)
    claim, merchant, store = locked_claim(db, actor, data)
    # A matching request may have committed while we waited for its locks.
    existing = db.scalar(
        select(Redemption).where(
            Redemption.actor_id == actor.id, Redemption.idempotency_key == idempotency_key
        )
    )
    if existing:
        if existing.request_hash != fingerprint(data):
            fail("This request key was already used for different redemption details.")
        return receipt(existing)
    now = datetime.now(UTC)
    offer = check_claim(claim, store, now)
    verify(request.app.state.settings, actor, data, claim, data.confirmation_token)
    discount = calculate(offer, data.purchase_amount, data.reward_value)
    claim.status = "REDEEMED"
    claim.redeemed_at = now
    row = Redemption(
        claim_id=claim.id,
        merchant_id=merchant.id,
        store_id=store.id,
        user_id=claim.user_id,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
        request_hash=fingerprint(data),
        purchase_amount=data.purchase_amount,
        discount_amount=discount,
        reward_value=data.reward_value,
        redeemed_at=now,
        receipt={
            "terms_confirmed": True,
            "title": offer.title,
            "business_name": claim.snapshot["business_name"],
            "store_name": store.name,
        },
    )
    db.add(row)
    try:
        db.flush()
        record(
            db,
            actor,
            merchant.id,
            "COUPON_REDEEMED",
            redemption_id=str(row.id),
            claim_id=str(claim.id),
            store_id=str(store.id),
            purchase_amount=str(row.purchase_amount),
            discount_amount=str(row.discount_amount),
        )
        enqueue(
            db,
            kind="coupon.redeemed",
            payload={"redemption_id": str(row.id)},
            key=f"coupon-redeemed:{row.id}",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("This coupon or request was already processed. Refresh redemption history.")
    return receipt(row)


@router.get("", response_model=list[Receipt])
def history(
    db: DB, actor: Actor, store_id: UUID, offset: int = Query(default=0, ge=0, le=10000)
) -> list[Receipt]:
    merchant, store = access(db, actor, store_id)
    query = select(Redemption).where(
        Redemption.merchant_id == merchant.id, Redemption.store_id == store.id
    )
    if actor.role == Role.MERCHANT_STAFF:
        query = query.where(Redemption.actor_id == actor.id)
    return [
        receipt(r)
        for r in db.scalars(
            query.order_by(Redemption.redeemed_at.desc(), Redemption.id).offset(offset).limit(25)
        )
    ]
