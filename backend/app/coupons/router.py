from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import delete, exists, select

from app.auth.dependencies import DB, csrf
from app.coupons.models import Campaign, CampaignBranch, CouponClaim
from app.coupons.schemas import (
    Allowance,
    CampaignAction,
    CampaignInput,
    CampaignOutput,
    CampaignUpdate,
    Receipt,
)
from app.coupons.service import (
    allowance,
    claim_coupon,
    eligible,
    fail,
    output,
    receipt,
    validate,
)
from app.offers.models import Category, Offer
from app.offers.public import Browse, public_query
from app.offers.service import record
from app.profiles.models import Merchant, Store
from app.profiles.router import Owner, Reviewer, Shopper, owned

router = APIRouter(prefix="/api/v1", tags=["Coupon campaigns"], dependencies=[Depends(csrf)])
public = APIRouter(prefix="/api/v1", tags=["Available coupons"])


def own_offer(db: DB, merchant: Merchant, offer_id: UUID) -> Offer:
    offer = db.scalar(
        select(Offer)
        .where(Offer.id == offer_id, Offer.merchant_id == merchant.id)
        .with_for_update()
    )
    if offer is None:
        fail("Offer not found.", 404)
    return offer


def own_campaign(db: DB, merchant: Merchant, campaign_id: UUID) -> tuple[Campaign, Offer]:
    offer_id = db.scalar(
        select(Campaign.offer_id)
        .join(Offer)
        .where(Campaign.id == campaign_id, Offer.merchant_id == merchant.id)
    )
    if offer_id is None:
        fail("Campaign not found.", 404)
    offer = own_offer(db, merchant, offer_id)
    db.scalar(select(Category).where(Category.id == offer.category_id).with_for_update())
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
    if not (campaign is not None):
        raise RuntimeError("Required application state is unavailable")
    return campaign, offer


def revision(campaign: Campaign, expected: int) -> None:
    if campaign.revision != expected:
        fail("This campaign changed. Reload before continuing.")


@router.get("/merchant/campaigns", response_model=list[CampaignOutput])
def listing(
    db: DB, user: Owner, offset: int = Query(default=0, ge=0, le=10000)
) -> list[CampaignOutput]:
    merchant = owned(db, user)
    rows = db.execute(
        select(Campaign, Offer)
        .join(Offer)
        .where(Offer.merchant_id == merchant.id)
        .order_by(Campaign.created_at.desc(), Campaign.id)
        .offset(offset)
        .limit(25)
    )
    return [output(db, campaign, offer) for campaign, offer in rows]


@router.get("/admin/campaigns", response_model=list[CampaignOutput])
def admin_listing(
    db: DB, user: Reviewer, offset: int = Query(default=0, ge=0, le=10000)
) -> list[CampaignOutput]:
    rows = db.execute(
        select(Campaign, Offer)
        .join(Offer)
        .order_by(Campaign.created_at.desc(), Campaign.id)
        .offset(offset)
        .limit(25)
    )
    return [output(db, campaign, offer) for campaign, offer in rows]


@router.post("/merchant/campaigns", response_model=CampaignOutput, status_code=201)
def create(data: CampaignInput, db: DB, user: Owner) -> CampaignOutput:
    merchant = owned(db, user)
    if merchant.status != "VERIFIED":
        fail("Your business must be verified to manage campaigns.")
    offer = own_offer(db, merchant, data.offer_id)
    validate(db, data, offer)
    campaign = Campaign(**data.model_dump(exclude={"store_ids"}))
    db.add(campaign)
    db.flush()
    db.add_all(CampaignBranch(campaign_id=campaign.id, store_id=s) for s in data.store_ids)
    record(db, user, merchant.id, "CAMPAIGN_CREATED", campaign_id=str(campaign.id))
    db.commit()
    return output(db, campaign, offer)


@router.put("/merchant/campaigns/{campaign_id}", response_model=CampaignOutput)
def update(campaign_id: UUID, data: CampaignUpdate, db: DB, user: Owner) -> CampaignOutput:
    merchant = owned(db, user)
    if merchant.status != "VERIFIED":
        fail("Your business must be verified to manage campaigns.")
    campaign, offer = own_campaign(db, merchant, campaign_id)
    revision(campaign, data.revision)
    if campaign.status == "CANCELLED" or data.offer_id != offer.id:
        fail("Cancelled campaigns and the linked offer cannot be changed.")
    if data.total_quantity < campaign.claimed_count:
        fail("Quantity cannot be lower than coupons already claimed.")
    before = output(db, campaign, offer)
    changes = data.model_dump(exclude={"revision", "total_quantity", "store_ids"})
    if campaign.claimed_count and (
        any(getattr(campaign, k) != v for k, v in changes.items())
        or set(data.store_ids) != set(before.store_ids)
    ):
        fail(
            "After the first claim, only total quantity can change. "
            "Create a new campaign for new terms."
        )
    validate(db, data, offer)
    for key, value in data.model_dump(exclude={"revision", "store_ids"}).items():
        setattr(campaign, key, value)
    db.execute(delete(CampaignBranch).where(CampaignBranch.campaign_id == campaign.id))
    db.add_all(CampaignBranch(campaign_id=campaign.id, store_id=s) for s in data.store_ids)
    if not campaign.claimed_count:
        campaign.status = "DRAFT"
    campaign.revision += 1
    record(db, user, merchant.id, "CAMPAIGN_UPDATED", campaign_id=str(campaign.id))
    db.commit()
    return output(db, campaign, offer)


@router.post("/merchant/campaigns/{campaign_id}/actions", response_model=CampaignOutput)
def action(campaign_id: UUID, data: CampaignAction, db: DB, user: Owner) -> CampaignOutput:
    merchant = owned(db, user)
    campaign, offer = own_campaign(db, merchant, campaign_id)
    revision(campaign, data.revision)
    if campaign.status == "CANCELLED":
        fail("This campaign is already cancelled.")
    if data.action == "ACTIVATE":
        if campaign.status not in {"DRAFT", "PAUSED"}:
            fail("Only draft or paused campaigns can be activated.")
        # Future campaigns may activate now, but cannot be claimed before their start.
        now = datetime.now(UTC)
        validate(
            db,
            CampaignInput.model_validate(
                output(db, campaign, offer).model_dump(include=set(CampaignInput.model_fields))
            ),
            offer,
        )
        campaign.status = "ACTIVE"
        eligible(db, campaign, offer, merchant, max(now, campaign.starts_at, offer.starts_at))
    elif data.action == "PAUSE":
        if campaign.status != "ACTIVE":
            fail("Only active campaigns can be paused.")
        campaign.status = "PAUSED"
    else:
        campaign.status = "CANCELLED"
    campaign.revision += 1
    record(db, user, merchant.id, "CAMPAIGN_" + data.action, campaign_id=str(campaign.id))
    db.commit()
    return output(db, campaign, offer)


@public.get("/offers/{offer_id}/campaigns", response_model=list[CampaignOutput])
def available(
    offer_id: UUID,
    db: DB,
    store_id: UUID | None = None,
    offset: int = Query(default=0, ge=0, le=10000),
) -> list[CampaignOutput]:
    if db.execute(public_query(Browse(), 5, offer_id, store_id)).first() is None:
        fail("Offer unavailable.", 404)
    now = datetime.now(UTC)
    branch = (
        select(CampaignBranch.campaign_id)
        .join(Store, Store.id == CampaignBranch.store_id)
        .where(
            CampaignBranch.campaign_id == Campaign.id,
            Store.status == "ACTIVE",
            Store.latitude.is_not(None),
            Store.merchant_id == Offer.merchant_id,
            (Offer.store_id.is_(None) | (Store.id == Offer.store_id)),
        )
    )
    if store_id:
        branch = branch.where(Store.id == store_id)
    rows = db.execute(
        select(Campaign, Offer)
        .join(Offer)
        .where(
            Campaign.offer_id == offer_id,
            Campaign.status == "ACTIVE",
            Campaign.starts_at <= now,
            Campaign.expires_at > now,
            Campaign.claimed_count < Campaign.total_quantity,
            exists(branch),
        )
        .order_by(Campaign.expires_at, Campaign.id)
        .offset(offset)
        .limit(25)
    )
    return [output(db, c, o) for c, o in rows]


@router.get("/shopper/allowance", response_model=Allowance)
def user_allowance(db: DB, user: Shopper) -> Allowance:
    return allowance(db, user.id, datetime.now(UTC))


@router.post("/shopper/campaigns/{campaign_id}/claim", response_model=Receipt)
def claim(
    campaign_id: UUID, db: DB, user: Shopper, idempotency_key: Annotated[UUID, Header()]
) -> Receipt:
    return claim_coupon(db, user, campaign_id, idempotency_key)


@router.get("/shopper/claims", response_model=list[Receipt])
def claims(db: DB, user: Shopper, offset: int = Query(default=0, ge=0, le=10000)) -> list[Receipt]:
    return [
        receipt(c)
        for c in db.scalars(
            select(CouponClaim)
            .where(CouponClaim.user_id == user.id)
            .order_by(CouponClaim.claimed_at.desc(), CouponClaim.id)
            .offset(offset)
            .limit(25)
        )
    ]
