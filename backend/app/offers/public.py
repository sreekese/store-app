from datetime import UTC, datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import Float, and_, cast, func, literal, or_, select
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.auth.dependencies import DB
from app.auth.service import AuthError
from app.daily.policy import Rules, active
from app.locations.router import visible
from app.locations.spatial import GeographyPoint
from app.offers.models import Category, Offer
from app.offers.schemas import OfferInput, PublicOffer, PublicPage
from app.profiles.models import Merchant, Store
from app.profiles.schemas import Input

router = APIRouter(prefix="/api/v1/offers", tags=["Public offers"])


class Browse(Input):
    store_id: UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    radius_km: float | None = Field(default=None, ge=0.1, le=100, allow_inf_nan=False)
    category_id: UUID | None = None
    q: str = Field(default="", max_length=100)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=12, ge=1, le=50)

    @model_validator(mode="after")
    def coordinate_pair(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Supply both coordinates")
        if self.radius_km is not None and self.latitude is None:
            raise ValueError("A radius requires a search centre")
        return self


def public_query(
    params: Browse, radius: float, offer_id: UUID | None = None, store_id: UUID | None = None
) -> Select[tuple[Offer, Merchant, Category, Store, float | None]]:
    store_id = store_id or params.store_id
    distance: ColumnElement[float] = cast(literal(None), Float)
    if params.latitude is not None:
        centre = cast(
            func.ST_SetSRID(func.ST_MakePoint(params.longitude, params.latitude), 4326),
            GeographyPoint(),
        )
        distance = func.ST_Distance(Store.location, centre)
    query = (
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
            Offer.status == "ACTIVE",
            Offer.approved.is_(True),
            Offer.admin_hold.is_(False),
            Offer.starts_at <= func.now(),
            Offer.expires_at > func.now(),
            Category.is_active.is_(True),
        )
    )
    if params.latitude is not None:
        query = query.where(func.ST_DWithin(Store.location, centre, radius * 1000))
    if params.category_id is not None:
        query = query.where(Offer.category_id == params.category_id)
    if params.q:
        query = query.where(
            or_(
                Offer.title.icontains(params.q, autoescape=True),
                Offer.description.icontains(params.q, autoescape=True),
                Merchant.business_name.icontains(params.q, autoescape=True),
            )
        )
    if offer_id is not None:
        query = query.where(Offer.id == offer_id)
    if store_id is not None:
        query = query.where(Store.id == store_id)
    # Filter eligible branches first, then choose one nearest branch per offer.
    matched = query.with_only_columns(
        Offer.id.label("offer_id"),
        Store.id.label("store_id"),
        distance.label("distance"),
        func.row_number().over(partition_by=Offer.id, order_by=(distance, Store.id)).label("rank"),
    ).subquery()
    result = (
        select(Offer, Merchant, Category, Store, matched.c.distance)
        .join(Merchant, Merchant.id == Offer.merchant_id)
        .join(Category, Category.id == Offer.category_id)
        .join(matched, matched.c.offer_id == Offer.id)
        .join(Store, Store.id == matched.c.store_id)
        .where(matched.c.rank == 1)
    )
    return (
        result.order_by(matched.c.distance, Offer.id)
        if params.latitude is not None
        else result.order_by(Offer.starts_at.desc(), Offer.id)
    )


def public_output(
    offer: Offer, merchant: Merchant, category: Category, store: Store, distance: float | None
) -> PublicOffer:
    if not (store.latitude is not None and store.longitude is not None):
        raise RuntimeError("Required application state is unavailable")
    data = {field: getattr(offer, field) for field in OfferInput.model_fields}
    return PublicOffer(
        **data,
        id=offer.id,
        business_name=merchant.business_name,
        category_name=category.name,
        matched_store_id=store.id,
        store_name=store.name,
        city=store.city,
        area=store.area,
        latitude=store.latitude,
        longitude=store.longitude,
        distance_meters=round(distance, 2) if distance is not None else None,
    )


@router.get("", response_model=PublicPage)
def browse(params: Annotated[Browse, Query()], db: DB, request: Request) -> PublicPage:
    settings = Rules.model_validate(active(db, datetime.now(UTC)).rules)
    radius = params.radius_km if params.radius_km is not None else settings.default_radius_km
    if radius > settings.max_radius_km:
        raise AuthError("INVALID_RADIUS", "The requested radius exceeds the discovery limit.", 422)
    rows = db.execute(
        public_query(params, radius).offset(params.offset).limit(params.limit + 1)
    ).all()
    return PublicPage(
        offers=[public_output(*row) for row in rows[: params.limit]],
        next_offset=params.offset + params.limit
        if len(rows) > params.limit and params.offset + params.limit <= 10000
        else None,
        radius_km=radius if params.latitude is not None else None,
    )


@router.get("/{offer_id}", response_model=PublicOffer)
def detail(offer_id: UUID, db: DB, store_id: UUID | None = None) -> PublicOffer:
    row = db.execute(public_query(Browse(), 5, offer_id, store_id)).first()
    if row is None:
        raise AuthError("OFFER_UNAVAILABLE", "This offer is unavailable, paused, or expired.", 404)
    return public_output(*row)
