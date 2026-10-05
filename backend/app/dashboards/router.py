from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text, true
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Subquery

from app.auth.dependencies import csrf, require_roles
from app.auth.models import Role, User
from app.auth.service import AuthError
from app.coupons.models import Campaign, CouponClaim
from app.offers.models import Offer
from app.profiles.models import Merchant, StaffAssignment, Store
from app.redemptions.models import Redemption

router = APIRouter(prefix="/api/v1/dashboards", tags=["Dashboards"], dependencies=[Depends(csrf)])
Manager = Annotated[User, Depends(require_roles(Role.MERCHANT))]
Administrator = Annotated[User, Depends(require_roles(Role.ADMIN, Role.SUPER_ADMIN))]
Staff = Annotated[User, Depends(require_roles(Role.MERCHANT_STAFF))]
Days = Annotated[int, Query(ge=7, le=90)]


def metrics(request: Request, actor: User, days: int) -> dict[str, object]:
    if days not in {7, 30, 90}:
        raise AuthError("INVALID_PERIOD", "Choose a 7, 30, or 90 day chart period.", 422)
    now = datetime.now(UTC)
    zone = ZoneInfo("Asia/Kolkata")
    today = now.astimezone(zone).date()
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, datetime.min.time(), zone)
    platform = actor.role in {Role.ADMIN, Role.SUPER_ADMIN}
    staff = actor.role == Role.MERCHANT_STAFF
    merchants = select(Merchant.id).where(Merchant.owner_id == actor.id)
    offers = (
        select(Offer.id) if platform else select(Offer.id).where(Offer.merchant_id.in_(merchants))
    )
    campaigns = select(Campaign.id).where(Campaign.offer_id.in_(offers))
    claims = select(CouponClaim).where(CouponClaim.campaign_id.in_(campaigns)).subquery()
    redemptions_query = select(Redemption)
    if staff:
        assigned = select(StaffAssignment.store_id).where(StaffAssignment.staff_id == actor.id)
        redemptions_query = redemptions_query.where(
            Redemption.actor_id == actor.id, Redemption.store_id.in_(assigned)
        )
    elif not platform:
        redemptions_query = redemptions_query.where(Redemption.merchant_id.in_(merchants))
    redemptions = redemptions_query.subquery()
    # One consistent read snapshot: never mix pre/post-redemption totals across queries.
    with Session(
        request.app.state.engine.execution_options(isolation_level="REPEATABLE READ")
    ) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        totals: dict[str, int | str | None] = {}
        if not staff:
            totals["stores"] = int(
                db.scalar(
                    select(func.count())
                    .select_from(Store)
                    .where(true() if platform else Store.merchant_id.in_(merchants))
                )
                or 0
            )
            totals["offers"] = int(
                db.scalar(select(func.count()).select_from(offers.subquery())) or 0
            )
            totals["campaigns"] = int(
                db.scalar(select(func.count()).select_from(campaigns.subquery())) or 0
            )
            totals["claims"] = int(db.scalar(select(func.count()).select_from(claims)) or 0)
            totals["active_coupons"] = int(
                db.scalar(
                    select(func.count())
                    .select_from(claims)
                    .where(claims.c.status == "CLAIMED", claims.c.expires_at > now)
                )
                or 0
            )
        if platform:
            totals["users"] = int(db.scalar(select(func.count()).select_from(User)) or 0)
            totals["merchants"] = int(db.scalar(select(func.count()).select_from(Merchant)) or 0)
        if staff:
            totals["assigned_branches"] = int(
                db.scalar(
                    select(func.count())
                    .select_from(StaffAssignment)
                    .where(StaffAssignment.staff_id == actor.id)
                )
                or 0
            )
        count, purchase, discount = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(redemptions.c.purchase_amount), 0),
                func.coalesce(func.sum(redemptions.c.discount_amount), 0),
            ).select_from(redemptions)
        ).one()
        totals.update(
            redemptions=count,
            recorded_purchase_amount=format(purchase, ".2f"),
            coupon_benefit_amount=format(discount, ".2f"),
        )
        if not staff:
            total_claims = int(totals["claims"] or 0)
            totals["redemption_rate"] = (
                str((Decimal(count) * 100 / total_claims).quantize(Decimal("0.01")))
                if total_claims
                else None
            )

        def daily(column: ColumnElement[datetime], source: Subquery) -> dict[date, int]:
            day = func.date(func.timezone("Asia/Kolkata", column))
            rows = db.execute(
                select(day, func.count())
                .select_from(source)
                .where(column >= start, column <= now)
                .group_by(day)
            ).all()
            return {day_value: count for day_value, count in rows}

        daily_claims = {} if staff else daily(claims.c.claimed_at, claims)
        daily_redemptions = daily(redemptions.c.redeemed_at, redemptions)
        activity = []
        for n in range(days):
            day_value = start_day + timedelta(days=n)
            row = {
                "date": day_value.isoformat(),
                "redemptions": daily_redemptions.get(day_value, 0),
            }
            if not staff:
                row["claims"] = daily_claims.get(day_value, 0)
            activity.append(row)
        top = []
        if not staff:
            ranked = db.execute(
                select(Campaign.offer_id, func.count().label("claims"))
                .join(CouponClaim, CouponClaim.campaign_id == Campaign.id)
                .where(
                    Campaign.offer_id.in_(offers),
                    CouponClaim.claimed_at >= start,
                    CouponClaim.claimed_at <= now,
                )
                .group_by(Campaign.offer_id)
                .order_by(func.count().desc(), Campaign.offer_id)
                .limit(5)
            ).all()
            for offer_id, claim_count in ranked:
                offer = db.get(Offer, offer_id)
                if not (offer is not None):
                    raise RuntimeError("Required application state is unavailable")
                top.append({"offer_id": str(offer_id), "title": offer.title, "claims": claim_count})
    return {
        "scope": "platform" if platform else "staff" if staff else "merchant",
        "generated_at": now.isoformat(),
        "timezone": "Asia/Kolkata",
        "days": days,
        "start_date": start_day.isoformat(),
        "end_date": today.isoformat(),
        "totals": totals,
        "daily": activity,
        "top_offers": top,
    }


@router.get("/merchant")
def merchant(request: Request, actor: Manager, days: Days = 30) -> dict[str, object]:
    return metrics(request, actor, days)


@router.get("/platform")
def platform(request: Request, actor: Administrator, days: Days = 30) -> dict[str, object]:
    return metrics(request, actor, days)


@router.get("/staff")
def staff(request: Request, actor: Staff, days: Days = 30) -> dict[str, object]:
    return metrics(request, actor, days)
