from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.auth.dependencies import DB, authenticated, csrf, require_roles
from app.auth.models import Role, User
from app.auth.service import AuthError
from app.coupons.models import CouponClaim
from app.jobs.models import Job
from app.notifications.models import Notification, NotificationPreference
from app.offers.service import record

router = APIRouter(
    prefix="/api/v1/notifications", tags=["Notifications"], dependencies=[Depends(csrf)]
)
Actor = Annotated[User, Depends(authenticated)]
Super = Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_enabled: bool = False
    daily_enabled: bool = True


@router.get("/preferences")
def preferences(db: DB, user: Actor) -> dict[str, Any]:
    row = db.get(NotificationPreference, user.id)
    return {
        "email_enabled": row.email_enabled if row else False,
        "daily_enabled": row.daily_enabled if row else True,
        "email_mode": "LOCAL_CAPTURE",
    }


@router.put("/preferences")
def update_preferences(data: Preferences, db: DB, user: Actor) -> dict[str, Any]:
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = db.get(NotificationPreference, user.id)
    if row is None:
        row = NotificationPreference(user_id=user.id)
        db.add(row)
    row.email_enabled = data.email_enabled
    row.daily_enabled = data.daily_enabled
    db.commit()
    return preferences(db, user)


def stale(db: DB, note: Notification) -> bool:
    if note.valid_until and note.valid_until <= datetime.now(UTC):
        return True
    if note.kind == "COUPON_EXPIRY_REMINDER":
        claim = db.get(CouponClaim, UUID(note.event_key.split(":")[-1]))
        return not claim or claim.status != "CLAIMED" or claim.expires_at <= datetime.now(UTC)
    return False


@router.get("")
def inbox(
    db: DB, user: Actor, unread: bool = False, offset: int = Query(0, ge=0, le=10000)
) -> dict[str, Any]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread:
        query = query.where(Notification.read_at.is_(None))
    rows = list(
        db.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id).offset(offset).limit(21)
        )
    )
    count = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    return {
        "unread_count": count,
        "next_offset": offset + 20 if len(rows) > 20 and offset + 20 <= 10000 else None,
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "body": r.body,
                "link": r.link,
                "created_at": r.created_at,
                "read_at": r.read_at,
                "stale": stale(db, r),
            }
            for r in rows[:20]
        ],
    }


@router.post("/read-all")
def read_all(db: DB, user: Actor) -> dict[str, bool]:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    return {"updated": True}


@router.post("/{notification_id}/read")
def read(notification_id: UUID, db: DB, user: Actor) -> dict[str, bool]:
    row = db.scalar(
        select(Notification.id).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if row is None:
        raise AuthError("NOT_FOUND", "Notification not found.", 404)
    db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    return {"updated": True}


@router.get("/operations/failed")
def failed(db: DB, user: Super, offset: int = Query(0, ge=0, le=10000)) -> list[dict[str, Any]]:
    return [
        {"id": j.id, "kind": j.kind, "attempts": j.attempts, "last_error": j.last_error}
        for j in db.scalars(
            select(Job)
            .where(
                Job.status == "failed",
                Job.kind.in_(
                    [
                        "notification.email",
                        "notification.daily",
                        "notification.expiry",
                        "notification.merchant_approved",
                        "notification.offer_reviewed",
                        "coupon.claimed",
                        "coupon.redeemed",
                    ]
                ),
            )
            .order_by(Job.created_at.desc(), Job.id)
            .offset(offset)
            .limit(25)
        )
    ]


@router.post("/operations/{job_id}/retry")
def retry(job_id: UUID, db: DB, user: Super) -> dict[str, bool]:
    row = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    allowed = {
        "notification.email",
        "notification.daily",
        "notification.expiry",
        "notification.merchant_approved",
        "notification.offer_reviewed",
        "coupon.claimed",
        "coupon.redeemed",
    }
    if row is None or row.status != "failed" or row.kind not in allowed:
        raise AuthError("NOT_RETRYABLE", "This job is not a failed notification job.", 409)
    record(
        db, user, None, "NOTIFICATION_RETRIED", job_id=str(row.id), previous_attempts=row.attempts
    )
    row.status = "pending"
    row.attempts = 0
    row.last_error = None
    row.available_at = datetime.now(UTC)
    db.commit()
    return {"queued": True}
