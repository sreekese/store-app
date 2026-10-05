import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import AuthError
from app.coupons.models import AllowanceUsage, Campaign, CampaignBranch, CouponClaim
from app.coupons.schemas import Allowance, CampaignInput, CampaignOutput, Receipt
from app.daily.policy import Rules, active, window
from app.jobs.service import enqueue
from app.offers.models import Category, Offer
from app.offers.schemas import OfferInput
from app.offers.service import record
from app.profiles.models import Merchant, Store


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("COUPON_REQUEST_DENIED", message, status)


def period(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(ZoneInfo("Asia/Kolkata")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def allowance(db: Session, user_id: UUID, now: datetime) -> Allowance:
    policy = active(db, now)
    rules = Rules.model_validate(policy.rules)
    start, end = window(policy, now)
    used = (
        db.scalar(
            select(func.count())
            .select_from(CouponClaim)
            .where(
                CouponClaim.user_id == user_id,
                CouponClaim.claimed_at >= start,
                CouponClaim.claimed_at < end,
            )
        )
        or 0
    )
    return Allowance(
        limit=rules.allowance,
        used=used,
        remaining=max(0, rules.allowance - used),
        resets_at=end,
        timezone=rules.timezone,
        policy_version=policy.version,
        period=rules.period,
    )


def status(campaign: Campaign, now: datetime | None = None) -> str:
    if campaign.status == "CANCELLED":
        return "CANCELLED"
    if campaign.expires_at <= (now or datetime.now(UTC)):
        return "EXPIRED"
    if campaign.status == "ACTIVE" and campaign.claimed_count >= campaign.total_quantity:
        return "SOLD_OUT"
    return campaign.status


def branches(db: Session, campaign: Campaign) -> list[Store]:
    return list(
        db.scalars(
            select(Store)
            .join(CampaignBranch, CampaignBranch.store_id == Store.id)
            .where(CampaignBranch.campaign_id == campaign.id)
            .order_by(Store.id)
        )
    )


def output(db: Session, campaign: Campaign, offer: Offer) -> CampaignOutput:
    return CampaignOutput(
        id=campaign.id,
        offer_id=offer.id,
        title=offer.title,
        store_ids=[s.id for s in branches(db, campaign)],
        total_quantity=campaign.total_quantity,
        per_user_limit=campaign.per_user_limit,
        validity_hours=campaign.validity_hours,
        starts_at=campaign.starts_at,
        expires_at=campaign.expires_at,
        status=status(campaign),
        revision=campaign.revision,
        claimed_count=campaign.claimed_count,
        available_count=campaign.total_quantity - campaign.claimed_count,
    )


def validate(db: Session, data: CampaignInput, offer: Offer) -> None:
    if (
        data.starts_at < offer.starts_at
        or data.expires_at > offer.expires_at
        or data.expires_at <= datetime.now(UTC)
    ):
        fail("Campaign dates must fall within the offer period and end in the future.", 422)
    stores = list(db.scalars(select(Store).where(Store.id.in_(data.store_ids))))
    if len(stores) != len(data.store_ids) or any(
        s.merchant_id != offer.merchant_id
        or (offer.store_id is not None and s.id != offer.store_id)
        for s in stores
    ):
        fail("Choose participating branches belonging to this offer.", 403)
    if any(s.status != "ACTIVE" or s.latitude is None for s in stores):
        fail("Participating branches must be active and have map coordinates.")


def eligible(
    db: Session, campaign: Campaign, offer: Offer, merchant: Merchant, now: datetime
) -> list[Store]:
    category = db.scalar(select(Category).where(Category.id == offer.category_id).with_for_update())
    owner_active = db.scalar(select(User.is_active).where(User.id == merchant.owner_id))
    if (
        merchant.status != "VERIFIED"
        or not owner_active
        or not category
        or not category.is_active
        or offer.status != "ACTIVE"
        or not offer.approved
        or offer.admin_hold
        or not (offer.starts_at <= now < offer.expires_at)
    ):
        fail("This offer is not currently available for coupon claims.")
    if status(campaign, now) != "ACTIVE" or not (campaign.starts_at <= now < campaign.expires_at):
        fail("This campaign is paused, not started, expired, or sold out.")
    stores = [
        s
        for s in branches(db, campaign)
        if s.status == "ACTIVE"
        and s.latitude is not None
        and s.merchant_id == merchant.id
        and (offer.store_id is None or s.id == offer.store_id)
    ]
    if not stores:
        fail("No participating branch is currently available.")
    return stores


def receipt(claim: CouponClaim) -> Receipt:
    return Receipt(
        id=claim.id,
        campaign_id=claim.campaign_id,
        title=str(claim.snapshot["offer"]["title"]),
        status="EXPIRED"
        if claim.status == "CLAIMED" and claim.expires_at <= datetime.now(UTC)
        else claim.status,
        claimed_at=claim.claimed_at,
        expires_at=claim.expires_at,
    )


def claim_coupon(db: Session, user: User, campaign_id: UUID, key: UUID) -> Receipt:
    # One user lock serializes allowance and idempotency across every campaign/device.
    # Merchant -> offer -> category -> campaign matches management mutation ordering.
    locked_user = db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not locked_user.is_active:
        fail("Please sign in again.", 401)
    existing = db.scalar(
        select(CouponClaim).where(
            CouponClaim.user_id == user.id, CouponClaim.idempotency_key == key
        )
    )
    if existing:
        if existing.campaign_id != campaign_id:
            fail("This request key was already used for another campaign.")
        return receipt(existing)
    candidate = db.execute(
        select(Campaign.offer_id, Offer.merchant_id)
        .join(Offer, Offer.id == Campaign.offer_id)
        .where(Campaign.id == campaign_id)
    ).first()
    if candidate is None:
        fail("Campaign not found.", 404)
    merchant = db.scalar(
        select(Merchant).where(Merchant.id == candidate.merchant_id).with_for_update()
    )
    offer = db.scalar(select(Offer).where(Offer.id == candidate.offer_id).with_for_update())
    if not (merchant is not None and offer is not None):
        raise RuntimeError("Required application state is unavailable")
    db.scalar(select(Category).where(Category.id == offer.category_id).with_for_update())
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not (campaign is not None):
        raise RuntimeError("Required application state is unavailable")
    # Read the wall clock after lock waits, not PostgreSQL transaction-start time.
    now = datetime.now(UTC)
    stores = eligible(db, campaign, offer, merchant, now)
    previous = (
        db.scalar(
            select(func.count())
            .select_from(CouponClaim)
            .where(CouponClaim.user_id == user.id, CouponClaim.campaign_id == campaign.id)
        )
        or 0
    )
    if previous >= campaign.per_user_limit:
        fail("You have reached this campaign’s per-user limit.")
    redeemed = (
        db.scalar(
            select(CouponClaim.id)
            .join(Campaign, Campaign.id == CouponClaim.campaign_id)
            .join(Offer, Offer.id == Campaign.offer_id)
            .where(
                CouponClaim.user_id == user.id,
                Offer.merchant_id == merchant.id,
                CouponClaim.status == "REDEEMED",
                CouponClaim.redeemed_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )
    if (offer.customer_type == "NEW_CUSTOMERS" and redeemed) or (
        offer.customer_type == "EXISTING_CUSTOMERS" and not redeemed
    ):
        fail(
            "Customer eligibility is based on prior successful redemptions "
            "with this business on this platform."
        )
    policy = active(db, now)
    start, end = window(policy, now)
    current_allowance = allowance(db, user.id, now)
    if current_allowance.remaining == 0:
        fail(f"Your coupon allowance is used. It resets at {end.isoformat()}.")
    usage = db.get(AllowanceUsage, (user.id, start))
    if usage is None:
        usage = AllowanceUsage(user_id=user.id, period_start=start, period_end=end, used=0)
        db.add(usage)
    usage.used = current_allowance.used + 1
    usage.policy_version = policy.version
    campaign.claimed_count += 1
    campaign.revision += 1
    expiry = (
        min(campaign.expires_at, offer.expires_at, now + timedelta(hours=campaign.validity_hours))
        if campaign.validity_hours
        else min(campaign.expires_at, offer.expires_at)
    )
    claim = CouponClaim(
        campaign_id=campaign.id,
        user_id=user.id,
        idempotency_key=key,
        claim_token=secrets.token_urlsafe(32),
        claimed_at=now,
        expires_at=expiry,
        snapshot={
            "offer": OfferInput.model_validate(offer, from_attributes=True).model_dump(mode="json"),
            "offer_id": str(offer.id),
            "merchant_id": str(merchant.id),
            "business_name": merchant.business_name,
            "eligibility": "EXISTING_CUSTOMER" if redeemed else "NEW_CUSTOMER",
            "policy_version": policy.version,
            "branches": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "address": s.address,
                    "city": s.city,
                    "timezone": s.timezone,
                    "hours": s.hours,
                }
                for s in stores
            ],
        },
    )
    db.add(claim)
    db.flush()
    record(
        db,
        user,
        merchant.id,
        "COUPON_CLAIMED",
        claim_id=str(claim.id),
        campaign_id=str(campaign.id),
    )
    enqueue(
        db,
        kind="coupon.claimed",
        payload={"claim_id": str(claim.id)},
        key=f"coupon-claimed:{claim.id}",
    )
    enqueue(
        db,
        kind="coupon.expire",
        payload={"claim_id": str(claim.id)},
        key=f"coupon-expire:{claim.id}",
        available_at=expiry,
    )
    db.commit()
    return receipt(claim)


def claim_event(db: Session, payload: dict[str, Any]) -> None:
    claim = db.get(CouponClaim, UUID(payload["claim_id"]))
    if claim:
        from app.notifications.events import claimed

        claimed(db, claim)
        record(
            db,
            None,
            UUID(claim.snapshot["merchant_id"]),
            "COUPON_CLAIM_PROCESSED",
            claim_id=str(claim.id),
        )


def expire_claim(db: Session, payload: dict[str, Any]) -> None:
    candidate = db.get(CouponClaim, UUID(payload["claim_id"]))
    if candidate is None:
        return
    db.scalar(select(User).where(User.id == candidate.user_id).with_for_update())
    db.scalar(
        select(Merchant)
        .where(Merchant.id == UUID(candidate.snapshot["merchant_id"]))
        .with_for_update()
    )
    db.expire(candidate)
    claim = db.scalar(
        select(CouponClaim).where(CouponClaim.id == UUID(payload["claim_id"])).with_for_update()
    )
    if claim and claim.status == "CLAIMED" and claim.expires_at <= datetime.now(UTC):
        claim.status = "EXPIRED"
        record(
            db, None, UUID(claim.snapshot["merchant_id"]), "COUPON_EXPIRED", claim_id=str(claim.id)
        )
