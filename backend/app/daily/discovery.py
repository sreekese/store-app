import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Row, String, case, cast, exists, func, select
from sqlalchemy.orm import aliased

from app.auth.dependencies import DB, require_roles
from app.auth.models import Role, User
from app.coupons.models import Campaign, CouponClaim
from app.coupons.service import allowance
from app.daily.models import DailyPick, Recommendation
from app.daily.policy import Rules, active, window
from app.daily.router import candidates_query, deny
from app.daily.router import router as router
from app.locations.spatial import GeographyPoint
from app.offers.models import Offer
from app.profiles.models import Store

Shopper = Annotated[User, Depends(require_roles(Role.USER))]


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_km: float | None = Field(default=None, ge=0.1, le=100, allow_inf_nan=False)
    offset: int = Field(default=0, ge=0, le=10000)


@router.post("/recommendations")
def recommend(data: Search, db: DB, user: Shopper) -> dict[str, Any]:
    result = build_recommendation(data, db, user)
    db.commit()
    return result


def build_recommendation(
    data: Search, db: DB, user: User, *, persist: bool = True
) -> dict[str, Any]:
    # Serialize durable selection and claiming for this shopper across devices.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    now = datetime.now(UTC)
    policy = active(db, now)
    rules = Rules.model_validate(policy.rules)
    radius = data.radius_km if data.radius_km is not None else rules.default_radius_km
    if radius > rules.max_radius_km:
        deny("Radius exceeds the current platform maximum. Refresh location settings.", 422)
    day = now.astimezone(ZoneInfo(rules.timezone)).date()
    centre = cast(
        func.ST_SetSRID(func.ST_MakePoint(data.longitude, data.latitude), 4326), GeographyPoint()
    )
    distance = func.ST_Distance(Store.location, centre)
    used = (
        select(func.count())
        .select_from(CouponClaim)
        .where(CouponClaim.user_id == user.id, CouponClaim.campaign_id == Campaign.id)
        .correlate(Campaign)
        .scalar_subquery()
    )
    redeemed = exists(
        select(CouponClaim.id)
        .where(
            CouponClaim.user_id == user.id,
            CouponClaim.status == "REDEEMED",
            CouponClaim.redeemed_at.is_not(None),
            CouponClaim.snapshot["merchant_id"].astext == cast(Store.merchant_id, String),
        )
        .correlate(Store)
    )
    merchant_pick, override = aliased(DailyPick), aliased(DailyPick)
    chosen = case(
        (override.store_id.is_not(None), override.campaign_id), else_=merchant_pick.campaign_id
    )
    query = (
        candidates_query(now, now + timedelta(microseconds=1))
        .add_columns(distance.label("distance"), (chosen == Campaign.id).label("daily_pick"))
        .outerjoin(
            merchant_pick,
            (merchant_pick.store_id == Store.id)
            & (merchant_pick.business_date == day)
            & (merchant_pick.source == "MERCHANT"),
        )
        .outerjoin(
            override,
            (override.store_id == Store.id)
            & (override.business_date == day)
            & (override.source == "SUPER_ADMIN"),
        )
        .where(
            func.ST_DWithin(Store.location, centre, radius * 1000),
            used < Campaign.per_user_limit,
            (Offer.customer_type == "ALL")
            | ((Offer.customer_type == "NEW_CUSTOMERS") & ~redeemed)
            | ((Offer.customer_type == "EXISTING_CUSTOMERS") & redeemed),
        )
        .order_by(
            distance,
            Offer.created_at.desc(),
            (Campaign.total_quantity - Campaign.claimed_count).desc(),
            Campaign.id,
            Store.id,
        )
    )
    context = {
        "latitude": data.latitude,
        "longitude": data.longitude,
        "radius_km": radius,
        "business_date": str(day),
        "period_start": window(policy, now)[0].isoformat(),
        "policy_version": policy.version,
    }
    identity = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    saved = db.get(Recommendation, (user.id, identity))
    selected = (
        db.execute(
            query.where(Campaign.id == saved.campaign_id, Store.id == saved.store_id).limit(1)
        ).first()
        if saved
        else None
    )
    if selected is None:
        selected = db.execute(query.limit(1)).first()
        if saved and persist:
            db.delete(saved)
            db.flush()
        if selected and persist:
            db.add(
                Recommendation(
                    user_id=user.id,
                    identity=identity,
                    campaign_id=selected[0].id,
                    store_id=selected[2].id,
                    context=context,
                    selected_at=now,
                )
            )

    def card(row: Row[Any]) -> dict[str, Any]:
        c, o, s, meters, featured = row
        return {
            "campaign_id": c.id,
            "offer_id": o.id,
            "title": o.title,
            "store_id": s.id,
            "store_name": s.name,
            "distance_meters": round(meters, 2),
            "daily_pick": bool(featured),
            "available": c.total_quantity - c.claimed_count,
            "expires_at": min(c.expires_at, o.expires_at),
        }

    picks = db.execute(query.where(chosen == Campaign.id).offset(data.offset).limit(13)).all()
    result = {
        "recommendation": card(selected) if selected else None,
        "daily_picks": [card(r) for r in picks[:12]],
        "next_offset": data.offset + 12 if len(picks) > 12 and data.offset + 12 <= 10000 else None,
        "allowance": allowance(db, user.id, now).model_dump(mode="json"),
        "context": context,
        "message": (
            "Recommendations do not reserve stock. Eligibility is checked again when you claim."
        ),
    }
    return result
