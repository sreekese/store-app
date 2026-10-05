from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.advertisements.models import Advertisement
from app.advertisements.service import eligible
from app.analytics.models import AnalyticsEvent
from app.analytics.schemas import EventInput
from app.auth.dependencies import DB, csrf, require_roles, throttle
from app.auth.models import Role, User
from app.auth.service import AuthError
from app.coupons.models import Campaign, CouponClaim
from app.locations.router import visible
from app.offers.models import Offer
from app.offers.public import Browse, public_query
from app.profiles.models import Store

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"], dependencies=[Depends(csrf)])
Shopper = Annotated[User, Depends(require_roles(Role.USER))]


@router.post("/events", status_code=204)
def event(data: EventInput, db: DB, user: Shopper, request: Request) -> Response:
    now = datetime.now(UTC)
    merchant_id = None
    valid = False
    if data.kind == "OFFER_VIEWED":
        row = db.execute(public_query(Browse(), 5, data.target_id)).first()
        if row:
            merchant_id, valid = row[0].merchant_id, True
    elif data.kind == "STORE_VIEWED":
        row_store = db.execute(visible().where(Store.id == data.target_id)).first()
        if row_store:
            merchant_id, valid = row_store[0].merchant_id, True
    elif data.kind == "COUPON_VIEWED":
        merchant_id = db.scalar(
            select(Offer.merchant_id)
            .join(Campaign, Campaign.offer_id == Offer.id)
            .join(CouponClaim, CouponClaim.campaign_id == Campaign.id)
            .where(CouponClaim.id == data.target_id, CouponClaim.user_id == user.id)
        )
        valid = merchant_id is not None
    else:
        ad = db.get(Advertisement, data.target_id)
        if (
            ad
            and ad.status == "ENABLED"
            and ad.starts_at <= now < ad.expires_at
            and eligible(db, ad)
        ):
            valid = True
            if ad.store_id:
                merchant_id = db.scalar(select(Store.merchant_id).where(Store.id == ad.store_id))
    if not valid:
        raise AuthError("ANALYTICS_TARGET_UNAVAILABLE", "Event target is unavailable.", 404)
    bucket = int(now.timestamp()) // 1800
    throttle(request, db, "analytics-events", str(user.id), 120)
    db.execute(
        insert(AnalyticsEvent)
        .values(
            user_id=user.id,
            merchant_id=merchant_id,
            kind=data.kind,
            target_id=data.target_id,
            bucket=bucket,
            occurred_at=now,
        )
        .on_conflict_do_nothing(constraint="analytics_event_dedup")
    )
    db.commit()
    return Response(status_code=204)
