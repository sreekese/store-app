from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import AuthError
from app.jobs.service import enqueue
from app.offers.models import Category, Offer
from app.offers.schemas import OfferOutput
from app.profiles.models import AuditEvent, Merchant, Store


def fail(message: str, status: int = 409) -> None:
    raise AuthError("OFFER_REQUEST_DENIED", message, status)


def record(
    db: Session, actor: User | None, merchant_id: UUID | None, action: str, **detail: object
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor.id if actor else None,
            merchant_id=merchant_id,
            action=action,
            detail=detail,
        )
    )


def effective_status(offer: Offer, now: datetime | None = None) -> str:
    if offer.status != "ARCHIVED" and offer.expires_at <= (now or datetime.now(UTC)):
        return "EXPIRED"
    return offer.status


def output(offer: Offer) -> OfferOutput:
    return OfferOutput.model_validate(offer).model_copy(update={"status": effective_status(offer)})


def check_revision(offer: Offer, revision: int) -> None:
    if offer.revision != revision:
        fail("This offer changed. Reload it before continuing.")


def require_publishable(db: Session, offer: Offer, merchant: Merchant) -> None:
    if merchant.status != "VERIFIED":
        fail("Your business must be verified to publish offers.")
    category = db.scalar(select(Category).where(Category.id == offer.category_id).with_for_update())
    if category is None or not category.is_active:
        fail("Choose an active category.")
    store_query = select(Store.id).where(
        Store.merchant_id == merchant.id, Store.status == "ACTIVE", Store.location.is_not(None)
    )
    if offer.store_id is not None:
        store_query = store_query.where(Store.id == offer.store_id)
    if db.scalar(store_query.limit(1)) is None:
        fail("Publishing requires an active branch with map coordinates.")
    if offer.expires_at <= datetime.now(UTC):
        fail("This offer has expired. Edit its dates before submitting it again.")


def validate_targets(
    db: Session, merchant: Merchant, category_id: UUID, store_id: UUID | None
) -> None:
    # Category deletion is serialized against offer creation/editing.
    category = db.scalar(select(Category).where(Category.id == category_id).with_for_update())
    if category is None or not category.is_active:
        fail("Choose an active category.", 422)
    if (
        store_id is not None
        and db.scalar(
            select(Store.id).where(Store.id == store_id, Store.merchant_id == merchant.id)
        )
        is None
    ):
        fail("Choose a branch belonging to your business.", 403)


def touch(offer: Offer) -> None:
    offer.revision += 1
    offer.updated_at = datetime.now(UTC)


def schedule_expiry(db: Session, offer: Offer) -> None:
    expiry = offer.expires_at.astimezone(UTC).isoformat()
    enqueue(
        db,
        kind="offer.expire",
        payload={"offer_id": str(offer.id), "expires_at": expiry},
        key=f"offer-expiry:{offer.id}:{expiry}",
        available_at=offer.expires_at,
    )


def expire_offer(db: Session, payload: dict[str, Any]) -> None:
    offer_id = UUID(payload["offer_id"])
    merchant_id = db.scalar(select(Offer.merchant_id).where(Offer.id == offer_id))
    if merchant_id is None:
        return
    db.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update())
    offer = db.scalar(select(Offer).where(Offer.id == offer_id).with_for_update())
    if offer is None or offer.expires_at != datetime.fromisoformat(payload["expires_at"]):
        return
    if offer.expires_at <= datetime.now(UTC) and offer.status not in {"ARCHIVED", "EXPIRED"}:
        offer.status = "EXPIRED"
        touch(offer)
        record(db, None, merchant_id, "OFFER_EXPIRED", offer_id=str(offer.id))
