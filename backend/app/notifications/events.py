from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, exists, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth.models import Role, User
from app.coupons.models import CouponClaim
from app.daily.discovery import Search, build_recommendation
from app.daily.models import Recommendation
from app.daily.policy import Rules, active
from app.jobs.models import Job
from app.jobs.service import enqueue
from app.notifications.models import NotificationPreference
from app.notifications.service import notify
from app.profiles.models import Merchant


def claimed(db: Session, claim: CouponClaim) -> None:
    notify(
        db,
        user_id=claim.user_id,
        key=f"claimed:{claim.id}",
        kind="COUPON_CLAIMED",
        title="Coupon claim recorded",
        body="Your coupon is in your wallet. Open it for current status and saved terms.",
        link=f"/app/coupons/{claim.id}",
    )
    now = datetime.now(UTC)
    if claim.status == "CLAIMED" and claim.expires_at > now:
        enqueue(
            db,
            kind="notification.expiry",
            payload={"claim_id": str(claim.id)},
            key=f"expiry-reminder:{claim.id}",
            available_at=max(now, claim.expires_at - timedelta(hours=1)),
        )


def expiry_reminder(db: Session, payload: dict[str, Any]) -> None:
    # Match the claim/redemption lock order; recheck status after waiting.
    candidate = db.get(CouponClaim, UUID(payload["claim_id"]))
    if candidate is None:
        return
    db.scalar(select(User).where(User.id == candidate.user_id).with_for_update())
    db.refresh(candidate)
    now = datetime.now(UTC)
    if candidate.status != "CLAIMED" or candidate.expires_at <= now:
        return
    notify(
        db,
        user_id=candidate.user_id,
        key=f"expiry:{candidate.id}",
        kind="COUPON_EXPIRY_REMINDER",
        title="Your coupon expires soon",
        body=(
            f"Expires at {candidate.expires_at.isoformat()}. "
            "Open your wallet to check availability and terms."
        ),
        link=f"/app/coupons/{candidate.id}",
        valid_until=candidate.expires_at,
    )


def merchant_approved(db: Session, payload: dict[str, Any]) -> None:
    merchant = db.get(Merchant, UUID(payload["merchant_id"]))
    if not merchant or merchant.status != "VERIFIED":
        return
    notify(
        db,
        user_id=merchant.owner_id,
        key=f"merchant-approved:{merchant.id}:{payload['revision']}",
        kind="MERCHANT_APPROVED",
        title="Your business was approved",
        body=(
            "Your business verification was approved. "
            "Open your workspace to manage your stores and offers."
        ),
        link="/merchant/dashboard",
    )


def daily_notification(db: Session, payload: dict[str, Any]) -> None:
    user_id = UUID(payload["user_id"])
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active or user.role != Role.USER:
        return
    pref = db.get(NotificationPreference, user_id)
    if pref and not pref.daily_enabled:
        return
    now = datetime.now(UTC)
    policy = active(db, now)
    rules = Rules.model_validate(policy.rules)
    day = now.astimezone(ZoneInfo(rules.timezone)).date()
    if payload["business_date"] != str(day):
        return
    last = db.scalar(
        select(Recommendation)
        .where(
            Recommendation.user_id == user_id,
            Recommendation.selected_at >= now - timedelta(days=30),
        )
        .order_by(Recommendation.selected_at.desc(), Recommendation.identity)
        .limit(1)
    )
    if not last:
        return
    result = build_recommendation(
        Search(
            latitude=last.context["latitude"],
            longitude=last.context["longitude"],
            radius_km=min(last.context["radius_km"], rules.max_radius_km),
        ),
        db,
        user,
        persist=False,
    )
    card = result["recommendation"]
    if not card or result["allowance"]["remaining"] == 0:
        return
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), ZoneInfo(rules.timezone))
    notify(
        db,
        user_id=user_id,
        key=f"daily:{day}",
        kind="DAILY_COUPON",
        title="A coupon suggestion for today",
        body=(
            f"{card['title']} near your last saved search area. "
            "Availability and allowance are checked when you claim."
        ),
        link=f"/offers/{card['offer_id']}?store_id={card['store_id']}",
        valid_until=min(end, card["expires_at"]),
    )


def schedule_daily(engine: Engine) -> int:
    """Bounded polling; durable per-user/date keys make concurrent schedulers safe."""
    now = datetime.now(UTC)
    with Session(engine) as db:
        policy = active(db, now)
        day = str(now.astimezone(ZoneInfo(policy.rules["timezone"])).date())
        key = "daily-notification:" + cast(User.id, String) + ":" + day
        users = list(
            db.scalars(
                select(User.id)
                .outerjoin(NotificationPreference)
                .where(
                    User.role == Role.USER,
                    User.is_active,
                    or_(
                        NotificationPreference.user_id.is_(None),
                        NotificationPreference.daily_enabled,
                    ),
                    exists(
                        select(Recommendation.user_id).where(
                            Recommendation.user_id == User.id,
                            Recommendation.selected_at >= now - timedelta(days=30),
                        )
                    ),
                    ~exists(select(Job.id).where(Job.deduplication_key == key)),
                )
                .order_by(User.id)
                .limit(100)
            )
        )
        for user_id in users:
            enqueue(
                db,
                kind="notification.daily",
                payload={"user_id": str(user_id), "business_date": day},
                key=f"daily-notification:{user_id}:{day}",
            )
        db.commit()
        return len(users)


def offer_reviewed(db: Session, payload: dict[str, Any]) -> None:
    from app.offers.models import Offer

    offer = db.get(Offer, UUID(payload["offer_id"]))
    merchant = db.get(Merchant, offer.merchant_id) if offer else None
    if not merchant:
        return
    decision = "approved" if payload["decision"] == "APPROVE" else "rejected"
    notify(
        db,
        user_id=merchant.owner_id,
        key=f"offer-reviewed:{payload['offer_id']}:{payload['revision']}",
        kind="OFFER_REVIEWED",
        title=f"Your offer was {decision}",
        body=f"{payload['title']}. Open your workspace for current status and review feedback.",
        link="/merchant/dashboard",
    )
