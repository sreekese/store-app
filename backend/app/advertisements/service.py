from datetime import UTC, datetime
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.advertisements.models import Advertisement
from app.advertisements.schemas import AdInput
from app.auth.service import AuthError
from app.locations.router import visible
from app.offers.models import Category, Offer
from app.offers.public import Browse, public_query
from app.profiles.models import Merchant, Store


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("ADVERTISEMENT_DENIED", message, status)


def offer_candidates(store_id: UUID | None) -> Select[tuple[Store, Merchant]]:
    # Approved future offers may be scheduled; serving rechecks availability at request time.
    return (
        visible()
        .join(
            Offer,
            and_(
                Offer.merchant_id == Merchant.id,
                or_(Offer.store_id.is_(None), Offer.store_id == Store.id),
            ),
        )
        .join(Category, Category.id == Offer.category_id)
        .where(
            Store.id == store_id,
            Offer.status == "ACTIVE",
            Offer.approved.is_(True),
            Offer.admin_hold.is_(False),
            Category.is_active.is_(True),
            Offer.expires_at > datetime.now(UTC),
        )
    )


def validate_target(db: Session, data: AdInput) -> None:
    if data.expires_at <= datetime.now(UTC):
        fail("The advertisement must end in the future.", 422)
    if data.destination_type == "DISCOVER":
        return
    if not db.execute(visible().where(Store.id == data.store_id)).first():
        fail("Choose an active branch of a verified business.", 422)
    if data.destination_type == "OFFER":
        row = db.scalar(
            offer_candidates(data.store_id)
            .with_only_columns(Offer)
            .where(Offer.id == data.offer_id)
        )
        if row is None or row.starts_at > data.starts_at or row.expires_at < data.expires_at:
            fail("Choose an approved offer at this branch whose dates cover the ad schedule.", 422)


def eligible(db: Session, row: Advertisement) -> bool:
    if row.destination_type == "DISCOVER":
        return True
    if row.store_id is None:
        return False
    if row.destination_type == "STORE":
        return db.execute(visible().where(Store.id == row.store_id)).first() is not None
    return (
        row.offer_id is not None
        and db.execute(public_query(Browse(), 5, row.offer_id, row.store_id)).first() is not None
    )


def card(row: Advertisement) -> dict[str, Any]:
    href = "/#discover"
    if row.destination_type == "STORE" and row.store_id:
        href = f"/stores/{row.store_id}"
    elif row.destination_type == "OFFER" and row.offer_id and row.store_id:
        href = f"/offers/{row.offer_id}?store_id={row.store_id}"
    return {
        "id": row.id,
        "sponsor": row.sponsor,
        "headline": row.headline,
        "body": row.body,
        "image_url": row.image_url,
        "image_alt": row.image_alt,
        "cta": row.cta,
        "placement": row.placement,
        "href": href,
        "valid_until": row.expires_at,
    }


def output(row: Advertisement) -> dict[str, Any]:
    return {
        **{key: getattr(row, key) for key in AdInput.model_fields},
        "id": row.id,
        "revision": row.revision,
        "status": row.status,
        "updated_at": row.updated_at,
    }


def conflicts(db: Session, row: Advertisement) -> bool:
    return (
        db.scalar(
            select(Advertisement.id)
            .where(
                Advertisement.id != row.id,
                Advertisement.status == "ENABLED",
                Advertisement.placement == row.placement,
                Advertisement.starts_at < row.expires_at,
                Advertisement.expires_at > row.starts_at,
            )
            .limit(1)
        )
        is not None
    )
