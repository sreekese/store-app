from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import User
from app.jobs.service import enqueue
from app.notifications.models import CapturedEmail, Notification, NotificationPreference


def notify(
    db: Session,
    *,
    user_id: UUID,
    key: str,
    kind: str,
    title: str,
    body: str,
    link: str,
    valid_until: datetime | None = None,
) -> None:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return
    preferences = db.get(NotificationPreference, user_id)
    if kind == "DAILY_COUPON" and preferences and not preferences.daily_enabled:
        return
    notification_id = db.scalar(
        insert(Notification)
        .values(
            user_id=user_id,
            event_key=key,
            kind=kind,
            title=title,
            body=body,
            link=link,
            valid_until=valid_until,
        )
        .on_conflict_do_nothing(constraint="notification_user_event")
        .returning(Notification.id)
    )
    if notification_id and preferences and preferences.email_enabled:
        enqueue(
            db,
            kind="notification.email",
            payload={"notification_id": str(notification_id)},
            key=f"notification-email:{notification_id}",
        )


class EmailTransport(Protocol):
    def send(
        self, db: Session, notification: Notification, recipient: str, *, idempotency_key: str
    ) -> None: ...


class CaptureEmail:
    """Local-only delivery adapter. Never sends network mail or logs message bodies.

    A future remote adapter must support the stable idempotency key: external delivery
    can succeed before the database transaction commits, so retries are at-least-once.
    """

    def send(
        self, db: Session, notification: Notification, recipient: str, *, idempotency_key: str
    ) -> None:
        db.execute(
            insert(CapturedEmail)
            .values(
                notification_id=notification.id,
                recipient=recipient,
                subject=notification.title,
                body=notification.body + "\n" + notification.link,
            )
            .on_conflict_do_nothing(index_elements=[CapturedEmail.notification_id])
        )


def email_delivery(
    db: Session, payload: dict[str, object], transport: EmailTransport | None = None
) -> None:
    note = db.get(Notification, UUID(str(payload["notification_id"])))
    if note is None:
        return
    user = db.get(User, note.user_id)
    pref = db.get(NotificationPreference, note.user_id)
    if not user or not user.is_active or not pref or not pref.email_enabled:
        return
    if note.kind == "DAILY_COUPON" and not pref.daily_enabled:
        return
    if note.valid_until and note.valid_until <= datetime.now(UTC):
        return
    # Revoked/expired coupon reminders are checked again even after email retry delay.
    if note.kind == "COUPON_EXPIRY_REMINDER":
        from app.coupons.models import CouponClaim

        claim = db.get(CouponClaim, UUID(note.event_key.split(":")[-1]))
        if not claim or claim.status != "CLAIMED" or claim.expires_at <= datetime.now(UTC):
            return
    (transport or CaptureEmail()).send(db, note, user.email, idempotency_key=str(note.id))
