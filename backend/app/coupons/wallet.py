from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import DB, csrf
from app.auth.models import User
from app.coupons.models import CouponClaim
from app.coupons.schemas import Receipt
from app.coupons.service import fail, receipt
from app.offers.schemas import OfferInput
from app.profiles.models import Merchant, Store
from app.profiles.router import Shopper
from app.redemptions.models import Redemption
from app.redemptions.schemas import Receipt as RedemptionReceipt
from app.redemptions.service import receipt as redemption_receipt

router = APIRouter(
    prefix="/api/v1/shopper/wallet", tags=["Private coupon wallet"], dependencies=[Depends(csrf)]
)


class WalletPage(BaseModel):
    claims: list[Receipt]
    next_offset: int | None


class WalletDetail(Receipt):
    redemption: RedemptionReceipt | None = None
    business_name: str
    offer: OfferInput
    eligibility: str
    branches: list[dict[str, Any]]
    redeemed_at: datetime | None
    claim_token: str | None
    availability_message: str
    server_time: datetime


@router.get("", response_model=WalletPage)
def listing(
    db: DB,
    user: Shopper,
    status: Literal["ACTIVE", "REDEEMED", "EXPIRED", "CANCELLED"] = "ACTIVE",
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=12, ge=1, le=50),
) -> WalletPage:
    now = datetime.now(UTC)
    query = select(CouponClaim).where(CouponClaim.user_id == user.id)
    if status == "ACTIVE":
        query = query.where(CouponClaim.status == "CLAIMED", CouponClaim.expires_at > now)
    elif status == "EXPIRED":
        query = query.where(
            (CouponClaim.status == "EXPIRED")
            | ((CouponClaim.status == "CLAIMED") & (CouponClaim.expires_at <= now))
        )
    else:
        query = query.where(CouponClaim.status == status)
    rows = list(
        db.scalars(
            query.order_by(CouponClaim.claimed_at.desc(), CouponClaim.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return WalletPage(
        claims=[receipt(c) for c in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit and offset + limit <= 10000 else None,
    )


@router.get("/{claim_id}", response_model=WalletDetail)
def detail(claim_id: UUID, db: DB, user: Shopper) -> WalletDetail:
    claim = db.scalar(
        select(CouponClaim).where(CouponClaim.id == claim_id, CouponClaim.user_id == user.id)
    )
    if claim is None:
        fail("Coupon not found in your wallet.", 404)
    now = datetime.now(UTC)
    summary = receipt(claim)
    snapshot = claim.snapshot
    merchant = db.get(Merchant, UUID(snapshot["merchant_id"]))
    merchant_available = bool(
        merchant
        and merchant.status == "VERIFIED"
        and db.scalar(select(User.is_active).where(User.id == merchant.owner_id))
    )
    saved_branches = snapshot["branches"]
    active_ids = set(
        db.scalars(
            select(Store.id).where(
                Store.id.in_([UUID(s["id"]) for s in saved_branches]),
                Store.merchant_id == UUID(snapshot["merchant_id"]),
                Store.status == "ACTIVE",
            )
        )
    )
    branches = [
        {**s, "currently_available": merchant_available and UUID(s["id"]) in active_ids}
        for s in saved_branches
    ]
    available = summary.status == "CLAIMED" and any(s["currently_available"] for s in branches)
    message = "Show this code only to authorized staff at a participating branch."
    if summary.status != "CLAIMED":
        message = "This coupon is " + summary.status.lower() + ". Its code is no longer available."
    elif not available:
        message = (
            "This business or its participating branches are temporarily unavailable. "
            "Your saved terms and expiry are unchanged. Check again before visiting."
        )
    redemption = db.scalar(select(Redemption).where(Redemption.claim_id == claim.id))
    return WalletDetail(
        redemption=redemption_receipt(redemption) if redemption else None,
        **summary.model_dump(),
        business_name=snapshot["business_name"],
        offer=OfferInput.model_validate(snapshot["offer"]),
        eligibility=snapshot["eligibility"],
        branches=branches,
        redeemed_at=claim.redeemed_at,
        claim_token=claim.claim_token if available else None,
        availability_message=message,
        server_time=now,
    )
