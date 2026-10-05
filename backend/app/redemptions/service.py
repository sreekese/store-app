import hashlib
import json
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NoReturn
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Role, User
from app.auth.service import AuthError
from app.core.config import Settings
from app.coupons.models import CouponClaim
from app.locations.router import is_open
from app.offers.schemas import OfferInput
from app.offers.service import record
from app.profiles.models import Merchant, StaffAssignment, Store
from app.profiles.schemas import HoursInput
from app.redemptions.models import Redemption
from app.redemptions.schemas import Receipt, ValidateInput


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("REDEMPTION_DENIED", message, status)


def access(db: Session, actor: User, store_id: UUID) -> tuple[Merchant, Store]:
    store = db.scalar(
        select(Store).where(Store.id == store_id).execution_options(populate_existing=True)
    )
    if store is None:
        fail("You do not have access to this branch.", 403)
    merchant = db.scalar(
        select(Merchant)
        .where(Merchant.id == store.merchant_id)
        .execution_options(populate_existing=True)
    )
    if not (merchant is not None):
        raise RuntimeError("Required application state is unavailable")
    permitted = (
        merchant.owner_id == actor.id
        if actor.role == Role.MERCHANT
        else db.scalar(
            select(StaffAssignment.staff_id).where(
                StaffAssignment.staff_id == actor.id, StaffAssignment.store_id == store.id
            )
        )
        is not None
    )
    if not permitted:
        fail("You do not have access to this branch.", 403)
    active = db.scalar(select(User.is_active).where(User.id == merchant.owner_id))
    actor_state = db.execute(select(User.is_active, User.role).where(User.id == actor.id)).first()
    if (
        not actor_state
        or not actor_state.is_active
        or actor_state.role not in {Role.MERCHANT, Role.MERCHANT_STAFF}
    ):
        fail("Your account no longer has redemption access.", 403)
    if merchant.status != "VERIFIED" or store.status != "ACTIVE" or not active:
        fail("This business or branch is not currently operational.")
    return merchant, store


def locked_claim(
    db: Session, actor: User, data: ValidateInput
) -> tuple[CouponClaim, Merchant, Store]:
    merchant, store = access(db, actor, data.store_id)
    candidate = db.execute(
        select(CouponClaim.id, CouponClaim.user_id).where(
            CouponClaim.claim_token == data.claim_token,
            CouponClaim.snapshot["merchant_id"].astext == str(merchant.id),
        )
    ).first()
    if candidate is None:
        fail("Coupon not found for this business.", 404)
    # Same parent-first order as claiming. This also avoids FK/user-lock deadlocks.
    shopper = db.scalar(
        select(User)
        .where(User.id == candidate.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.scalar(select(Merchant).where(Merchant.id == merchant.id).with_for_update())
    db.expire_all()
    merchant, store = access(db, actor, data.store_id)
    if shopper is None or not shopper.is_active:
        fail("This shopper account is unavailable.")
    claim = db.scalar(select(CouponClaim).where(CouponClaim.id == candidate.id).with_for_update())
    if claim is None:
        fail("Coupon not found for this business.", 404)
    return claim, merchant, store


def check_claim(claim: CouponClaim, store: Store, now: datetime) -> OfferInput:
    if claim.status != "CLAIMED":
        fail("This coupon is already redeemed, expired, or cancelled.")
    if claim.expires_at <= now:
        fail("This coupon has expired.")
    saved = next((s for s in claim.snapshot["branches"] if s["id"] == str(store.id)), None)
    if saved is None:
        fail("This branch does not participate in the saved coupon.", 403)
    # Empty hours are unknown, not closed. Published current and saved hours both apply.
    if is_open([HoursInput.model_validate(h) for h in store.hours], store.timezone, now) is False:
        fail("This branch is outside its current opening hours.")
    if (
        is_open([HoursInput.model_validate(h) for h in saved["hours"]], saved["timezone"], now)
        is False
    ):
        fail("This coupon is outside its saved branch opening hours.")
    return OfferInput.model_validate(claim.snapshot["offer"])


def calculate(offer: OfferInput, purchase: Decimal, reward: Decimal | None) -> Decimal:
    if purchase < offer.minimum_purchase:
        fail("The eligible purchase is below the saved minimum spend.", 422)
    if offer.discount_type not in {"BOGO", "FREE_ITEM"} and reward is not None:
        fail("A free-item value applies only to BOGO or free-item offers.", 422)
    if offer.discount_type == "PERCENTAGE":
        benefit = purchase * offer.discount_value / 100
        if offer.maximum_discount is not None:
            benefit = min(benefit, offer.maximum_discount)
    elif offer.discount_type == "FLAT_AMOUNT":
        benefit = offer.discount_value
    elif offer.discount_type == "SPECIAL_PRICE":
        if purchase < offer.discount_value:
            fail("The eligible original total cannot be below the saved special price.", 422)
        benefit = purchase - offer.discount_value
    else:
        if reward is None or reward > purchase:
            fail("Enter the free item's regular value within the eligible original total.", 422)
        if offer.discount_type == "BOGO" and reward * 2 > purchase:
            fail("BOGO requires a paid qualifying item worth at least the free item.", 422)
        benefit = reward
    return min(purchase, benefit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fingerprint(data: ValidateInput) -> str:
    payload = {
        "store_id": str(data.store_id),
        "claim_token": data.claim_token,
        "purchase_amount": format(data.purchase_amount, ".2f"),
        "reward_value": format(data.reward_value, ".2f") if data.reward_value is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def confirmation(
    settings: Settings, actor: User, data: ValidateInput, claim: CouponClaim, now: datetime
) -> tuple[str, datetime]:
    until = min(claim.expires_at, now + timedelta(minutes=5))
    token = jwt.encode(
        {
            "sub": str(actor.id),
            "purpose": "redeem",
            "claim": str(claim.id),
            "request": fingerprint(data),
            "exp": until,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    return token, until


def verify(
    settings: Settings, actor: User, data: ValidateInput, claim: CouponClaim, token: str
) -> None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "purpose", "claim", "request"]},
        )
        if (
            payload["sub"] != str(actor.id)
            or payload["purpose"] != "redeem"
            or payload["claim"] != str(claim.id)
            or payload["request"] != fingerprint(data)
        ):
            raise ValueError("Mismatched confirmation")
    except (jwt.InvalidTokenError, ValueError):
        fail("Validation expired or inputs changed. Validate the coupon again.")


def receipt(row: Redemption) -> Receipt:
    return Receipt(
        id=row.id,
        claim_id=row.claim_id,
        store_id=row.store_id,
        actor_id=row.actor_id,
        title=row.receipt["title"],
        business_name=row.receipt["business_name"],
        store_name=row.receipt["store_name"],
        redeemed_at=row.redeemed_at,
        purchase_amount=row.purchase_amount,
        discount_amount=row.discount_amount,
        payable_amount=row.purchase_amount - row.discount_amount,
    )


def redeemed_event(db: Session, payload: dict[str, Any]) -> None:
    row = db.get(Redemption, UUID(payload["redemption_id"]))
    if row:
        from app.notifications.service import notify

        notify(
            db,
            user_id=row.user_id,
            key=f"redeemed:{row.id}",
            kind="COUPON_REDEEMED",
            title="Coupon redemption recorded",
            body="Your redemption receipt is available in your wallet.",
            link=f"/app/coupons/{row.claim_id}",
        )
        record(db, None, row.merchant_id, "COUPON_REDEMPTION_PROCESSED", redemption_id=str(row.id))
