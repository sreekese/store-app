from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, literal_column, select, true, union_all
from sqlalchemy.orm import Session

from app.analytics.models import AnalyticsEvent
from app.analytics.schemas import Filters
from app.auth.models import Role, User
from app.auth.service import AuthError
from app.billing.models import Payment, Refund
from app.coupons.models import Campaign, CouponClaim
from app.offers.models import Offer
from app.profiles.models import Merchant
from app.redemptions.models import Redemption

ZONE = ZoneInfo("Asia/Kolkata")


def period(filters: Filters, now: datetime) -> tuple[datetime, datetime, datetime]:
    days = (filters.end_date - filters.start_date).days + 1
    if (
        days < 1
        or days > 366
        or filters.start_date < date(2000, 1, 1)
        or filters.end_date > now.astimezone(ZONE).date()
    ):
        raise AuthError("ANALYTICS_PERIOD", "Choose 1–366 days ending today or earlier.", 422)
    start = datetime.combine(filters.start_date, time.min, ZONE)
    end = min(datetime.combine(filters.end_date + timedelta(days=1), time.min, ZONE), now)
    previous = start - timedelta(days=days)
    return start, end, previous


def rate(numerator: int, denominator: int) -> str | None:
    return (
        str((Decimal(numerator) * 100 / denominator).quantize(Decimal("0.01")))
        if denominator
        else None
    )


def pairs(rows: Iterable[Any]) -> dict[Any, int]:
    return {key: int(value) for key, value in rows}


def report(
    db: Session, actor: User, filters: Filters, now: datetime, export: str | None = None
) -> dict[str, Any]:
    start, end, previous = period(filters, now)
    platform = actor.role in {Role.ADMIN, Role.SUPER_ADMIN}
    merchant_id = filters.merchant_id
    if not platform:
        own = db.scalar(select(Merchant.id).where(Merchant.owner_id == actor.id))
        if merchant_id is not None and merchant_id != own:
            raise AuthError("ANALYTICS_SCOPE", "Business not found.", 404)
        # An account without a business gets empty reports, never platform data.
        scope = Merchant.owner_id == actor.id
    else:
        scope = Merchant.id == merchant_id if merchant_id else true()
        if merchant_id and db.get(Merchant, merchant_id) is None:
            raise AuthError("ANALYTICS_SCOPE", "Business not found.", 404)
    merchants = select(Merchant.id).where(scope)
    campaigns = (
        select(Campaign.id)
        .join(Offer, Offer.id == Campaign.offer_id)
        .where(Offer.merchant_id.in_(merchants))
    )
    claims = (
        select(CouponClaim, Offer.merchant_id)
        .join(Campaign, Campaign.id == CouponClaim.campaign_id)
        .join(Offer, Offer.id == Campaign.offer_id)
        .where(Offer.merchant_id.in_(merchants))
        .subquery()
    )
    redemptions = (
        select(Redemption, CouponClaim.campaign_id)
        .join(CouponClaim, CouponClaim.id == Redemption.claim_id)
        .where(Redemption.merchant_id.in_(merchants))
        .subquery()
    )
    events = (
        select(AnalyticsEvent)
        .where(
            true() if platform and not merchant_id else AnalyticsEvent.merchant_id.in_(merchants)
        )
        .subquery()
    )
    current_claims = (
        select(claims).where(claims.c.claimed_at >= start, claims.c.claimed_at < end).subquery()
    )
    current_redemptions = (
        select(redemptions)
        .where(redemptions.c.redeemed_at >= start, redemptions.c.redeemed_at < end)
        .subquery()
    )
    claim_count = int(db.scalar(select(func.count()).select_from(current_claims)) or 0)
    redeemed_cohort = int(
        db.scalar(
            select(func.count())
            .select_from(current_claims)
            .join(
                Redemption,
                and_(Redemption.claim_id == current_claims.c.id, Redemption.redeemed_at < end),
            )
        )
        or 0
    )
    redemption_count, purchase, discount = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(current_redemptions.c.purchase_amount), 0),
            func.coalesce(func.sum(current_redemptions.c.discount_amount), 0),
        )
    ).one()
    # Transaction records are authoritative; client events cannot supply claim/payment success.
    activity = union_all(
        select(claims.c.user_id, claims.c.claimed_at.label("at")),
        select(redemptions.c.user_id, redemptions.c.redeemed_at.label("at")),
        select(events.c.user_id, events.c.occurred_at.label("at")),
    ).subquery()

    def users_between(a: datetime, b: datetime) -> Any:
        return select(activity.c.user_id).where(activity.c.at >= a, activity.c.at < b).distinct()

    engaged = int(
        db.scalar(select(func.count()).select_from(users_between(start, end).subquery())) or 0
    )
    end_midnight = datetime.combine(filters.end_date, time.min, ZONE)
    dau = int(
        db.scalar(select(func.count()).select_from(users_between(end_midnight, end).subquery()))
        or 0
    )
    mau = int(
        db.scalar(
            select(func.count()).select_from(
                users_between(end_midnight - timedelta(days=29), end).subquery()
            )
        )
        or 0
    )
    repeated = (
        select(current_claims.c.user_id)
        .group_by(current_claims.c.user_id)
        .having(func.count() > 1)
        .subquery()
    )
    transactional = union_all(
        select(claims.c.merchant_id, claims.c.claimed_at.label("at")),
        select(redemptions.c.merchant_id, redemptions.c.redeemed_at.label("at")),
    ).subquery()
    active = (
        select(transactional.c.merchant_id)
        .where(transactional.c.at >= start, transactional.c.at < end)
        .distinct()
    )
    prior = (
        select(transactional.c.merchant_id)
        .where(transactional.c.at >= previous, transactional.c.at < start)
        .distinct()
    )
    prior_count = int(db.scalar(select(func.count()).select_from(prior.subquery())) or 0)
    retained = int(
        db.scalar(
            select(func.count()).select_from(
                active.where(transactional.c.merchant_id.in_(prior)).subquery()
            )
        )
        or 0
    )
    daily_claims = pairs(
        db.execute(
            select(
                func.date(
                    func.timezone(literal_column("'Asia/Kolkata'"), current_claims.c.claimed_at)
                ),
                func.count(),
            ).group_by(
                func.date(
                    func.timezone(literal_column("'Asia/Kolkata'"), current_claims.c.claimed_at)
                )
            )
        ).all()
    )
    daily_redemptions = pairs(
        db.execute(
            select(
                func.date(
                    func.timezone(
                        literal_column("'Asia/Kolkata'"), current_redemptions.c.redeemed_at
                    )
                ),
                func.count(),
            ).group_by(
                func.date(
                    func.timezone(
                        literal_column("'Asia/Kolkata'"), current_redemptions.c.redeemed_at
                    )
                )
            )
        ).all()
    )
    daily_users = pairs(
        db.execute(
            select(
                func.date(func.timezone(literal_column("'Asia/Kolkata'"), activity.c.at)),
                func.count(func.distinct(activity.c.user_id)),
            )
            .where(activity.c.at >= start, activity.c.at < end)
            .group_by(func.date(func.timezone(literal_column("'Asia/Kolkata'"), activity.c.at)))
        ).all()
    )
    daily = []
    for n in range((filters.end_date - filters.start_date).days + 1):
        day = filters.start_date + timedelta(days=n)
        daily.append(
            {
                "date": day.isoformat(),
                "claims": daily_claims.get(day, 0),
                "redemptions": daily_redemptions.get(day, 0),
                "engaged_shoppers": daily_users.get(day, 0),
            }
        )

    def grouped(column: Any, base: Any) -> Any:
        return (
            select(column.label("id"), func.count().label("count"))
            .select_from(base)
            .group_by(column)
            .subquery()
        )

    cg = grouped(current_claims.c.campaign_id, current_claims)
    rg = grouped(current_redemptions.c.campaign_id, current_redemptions)
    cohort = (
        select(current_claims.c.campaign_id.label("id"), func.count().label("count"))
        .join(
            Redemption,
            and_(Redemption.claim_id == current_claims.c.id, Redemption.redeemed_at < end),
        )
        .group_by(current_claims.c.campaign_id)
        .subquery()
    )
    campaign_query = (
        select(
            Campaign.id,
            Offer.title,
            Campaign.status,
            func.coalesce(cg.c.count, 0).label("claims"),
            func.coalesce(rg.c.count, 0).label("redemptions"),
            func.coalesce(cohort.c.count, 0).label("cohort_redeemed"),
        )
        .join(Offer, Offer.id == Campaign.offer_id)
        .outerjoin(cg, cg.c.id == Campaign.id)
        .outerjoin(rg, rg.c.id == Campaign.id)
        .outerjoin(cohort, cohort.c.id == Campaign.id)
        .where(Campaign.id.in_(campaigns))
        .order_by(func.coalesce(cg.c.count, 0).desc(), Campaign.id)
    )
    limit = 10001 if export else 21
    offset = 0 if export else filters.campaign_offset
    campaign_rows = [
        {**dict(r._mapping), "cohort_rate": rate(r.cohort_redeemed, r.claims)}
        for r in db.execute(campaign_query.offset(offset).limit(limit))
    ]
    mg = grouped(current_claims.c.merchant_id, current_claims)
    mr = grouped(current_redemptions.c.merchant_id, current_redemptions)
    merchant_query = (
        select(
            Merchant.id,
            Merchant.business_name,
            Merchant.status,
            func.coalesce(mg.c.count, 0).label("claims"),
            func.coalesce(mr.c.count, 0).label("redemptions"),
        )
        .outerjoin(mg, mg.c.id == Merchant.id)
        .outerjoin(mr, mr.c.id == Merchant.id)
        .where(scope)
        .order_by(func.coalesce(mg.c.count, 0).desc(), Merchant.id)
    )
    merchant_rows = [
        dict(r._mapping)
        for r in db.execute(
            merchant_query.offset(0 if export else filters.merchant_offset).limit(limit)
        )
    ]
    event_counts = pairs(
        db.execute(
            select(events.c.kind, func.count())
            .where(events.c.occurred_at >= start, events.c.occurred_at < end)
            .group_by(events.c.kind)
        ).all()
    )
    event_counts.update(COUPON_CLAIMED=claim_count, COUPON_REDEEMED=redemption_count)
    if platform and not merchant_id:
        event_counts["USER_REGISTERED"] = int(
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == Role.USER, User.created_at >= start, User.created_at < end)
            )
            or 0
        )
    result: dict[str, Any] = {
        "scope": "platform" if platform else "merchant",
        "timezone": "Asia/Kolkata",
        "generated_at": now,
        "start_date": filters.start_date,
        "end_date": filters.end_date,
        "as_of": end,
        "summary": {
            "claims": claim_count,
            "redemptions": redemption_count,
            "cohort_redeemed": redeemed_cohort,
            "cohort_rate": rate(redeemed_cohort, claim_count),
            "recorded_purchase_amount": format(purchase, ".2f"),
            "coupon_benefit_amount": format(discount, ".2f"),
            "engaged_shoppers": engaged,
            "dau": dau,
            "mau": mau,
            "repeat_claimants": int(db.scalar(select(func.count()).select_from(repeated)) or 0),
        },
        "retention": {
            "previous_start_date": previous.date(),
            "previous_end_date": filters.start_date - timedelta(days=1),
            "previous_active_merchants": prior_count,
            "retained_merchants": retained,
            "rate": rate(retained, prior_count),
        },
        "events": [{"kind": k, "count": v} for k, v in sorted(event_counts.items())],
        "daily": daily,
        "campaigns": {
            "items": campaign_rows if export else campaign_rows[:20],
            "next_offset": offset + 20
            if not export and len(campaign_rows) > 20 and offset < 10000
            else None,
        },
        "merchants": {
            "items": merchant_rows if export else merchant_rows[:20],
            "next_offset": filters.merchant_offset + 20
            if not export and len(merchant_rows) > 20 and filters.merchant_offset < 10000
            else None,
        },
    }
    if actor.role == Role.SUPER_ADMIN:
        paid = (
            select(
                Payment.provider,
                Payment.currency,
                func.sum(Payment.amount_minor).label("amount"),
                func.count().label("count"),
            )
            .where(
                Payment.paid_at >= start, Payment.paid_at < end, Payment.merchant_id.in_(merchants)
            )
            .group_by(Payment.provider, Payment.currency)
        )
        refunded = (
            select(
                Payment.provider, Payment.currency, func.sum(Payment.amount_minor).label("amount")
            )
            .join(Refund, Refund.payment_id == Payment.id)
            .where(
                Refund.status == "COMPLETED",
                Refund.completed_at >= start,
                Refund.completed_at < end,
                Payment.merchant_id.in_(merchants),
            )
            .group_by(Payment.provider, Payment.currency)
        )
        money: dict[tuple[str, str], dict[str, Any]] = {}
        for p in db.execute(paid):
            money[(p.provider, p.currency)] = {
                "provider": p.provider,
                "currency": p.currency,
                "gross_minor": p.amount,
                "refund_minor": 0,
                "payments": p._mapping["count"],
            }
        for r in db.execute(refunded):
            money.setdefault(
                (r.provider, r.currency),
                {
                    "provider": r.provider,
                    "currency": r.currency,
                    "gross_minor": 0,
                    "refund_minor": 0,
                    "payments": 0,
                },
            )["refund_minor"] = r.amount
        result["revenue"] = [
            {**v, "net_minor": v["gross_minor"] - v["refund_minor"]}
            for _, v in sorted(money.items())
        ]
        result["events"].append(
            {"kind": "PAYMENT_COMPLETED", "count": sum(v["payments"] for v in money.values())}
        )
    if (export == "campaigns" and len(campaign_rows) > 10000) or (
        export == "merchants" and len(merchant_rows) > 10000
    ):
        raise AuthError(
            "EXPORT_TOO_LARGE", "Report exceeds 10,000 rows. Filter to a business.", 422
        )
    return result
