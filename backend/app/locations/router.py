from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, or_, select
from sqlalchemy.sql import Select

from app.auth.dependencies import DB
from app.auth.models import User
from app.auth.service import AuthError
from app.daily.policy import Rules, active
from app.locations.spatial import GeographyPoint
from app.profiles.models import Merchant, Store
from app.profiles.schemas import HoursInput, Input, minutes

router = APIRouter(prefix="/api/v1/locations", tags=["Store discovery"])


class Point(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class PublicStore(BaseModel):
    id: UUID
    name: str
    business_name: str
    category: str
    address: str
    city: str
    area: str
    state: str
    country: str
    postal_code: str
    phone: str
    latitude: float
    longitude: float
    geometry: Point
    timezone: str
    hours: list[HoursInput]
    is_open: bool | None
    distance_meters: float | None = None


class NearbyInput(Input):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_km: float | None = Field(default=None, ge=0.1, le=100, allow_inf_nan=False)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=25, ge=1, le=50)


class NearbyOutput(BaseModel):
    centre: Point
    radius_km: float
    stores: list[PublicStore]
    next_offset: int | None


def is_open(hours: list[HoursInput], timezone: str, now: datetime) -> bool | None:
    if not hours:
        return None
    local = now.astimezone(ZoneInfo(timezone))
    day, clock = local.weekday(), local.hour * 60 + local.minute
    for entry in hours:
        if entry.is_closed or entry.open_time is None or entry.close_time is None:
            continue
        start, end = minutes(entry.open_time), minutes(entry.close_time)
        if entry.day_of_week == day:
            if entry.closes_next_day and clock >= start:
                return True
            if not entry.closes_next_day and start <= clock < end:
                return True
        if entry.closes_next_day and (entry.day_of_week + 1) % 7 == day and clock < end:
            return True
    return False


def visible() -> Select[tuple[Store, Merchant]]:
    return (
        select(Store, Merchant)
        .join(Merchant, Merchant.id == Store.merchant_id)
        .join(User, User.id == Merchant.owner_id)
        .where(
            Store.status == "ACTIVE",
            Store.location.is_not(None),
            Merchant.status == "VERIFIED",
            User.is_active.is_(True),
        )
    )


def public_store(
    store: Store, merchant: Merchant, now: datetime, distance: float | None = None
) -> PublicStore:
    if not (store.latitude is not None and store.longitude is not None):
        raise RuntimeError("Required application state is unavailable")
    hours = [HoursInput.model_validate(item) for item in store.hours]
    return PublicStore(
        id=store.id,
        name=store.name,
        business_name=merchant.business_name,
        category=merchant.category,
        address=store.address,
        city=store.city,
        area=store.area,
        state=store.state,
        country=store.country,
        postal_code=store.postal_code,
        phone=store.phone or merchant.phone,
        latitude=store.latitude,
        longitude=store.longitude,
        geometry=Point(coordinates=(store.longitude, store.latitude)),
        timezone=store.timezone,
        hours=hours,
        is_open=is_open(hours, store.timezone, now),
        distance_meters=round(distance, 2) if distance is not None else None,
    )


@router.get("/config")
def discovery_config(db: DB) -> dict[str, float]:
    settings = Rules.model_validate(active(db, datetime.now(UTC)).rules)
    return {
        "default_radius_km": settings.default_radius_km,
        "max_radius_km": settings.max_radius_km,
    }


@router.get("/nearby", response_model=NearbyOutput)
def nearby(params: Annotated[NearbyInput, Query()], db: DB, request: Request) -> NearbyOutput:
    settings = Rules.model_validate(active(db, datetime.now(UTC)).rules)
    radius = params.radius_km if params.radius_km is not None else settings.default_radius_km
    if radius > settings.max_radius_km:
        raise AuthError("INVALID_RADIUS", "The requested radius exceeds the discovery limit.", 422)
    centre = cast(
        func.ST_SetSRID(func.ST_MakePoint(params.longitude, params.latitude), 4326),
        GeographyPoint(),
    )
    distance = func.ST_Distance(Store.location, centre).label("distance")
    query = (
        visible()
        .add_columns(distance)
        .where(func.ST_DWithin(Store.location, centre, radius * 1000))
        .order_by(distance, Store.id)
        .offset(params.offset)
        .limit(params.limit + 1)
    )
    rows = db.execute(query).all()
    now = datetime.now(UTC)
    return NearbyOutput(
        centre=Point(coordinates=(params.longitude, params.latitude)),
        radius_km=radius,
        stores=[public_store(row[0], row[1], now, row[2]) for row in rows[: params.limit]],
        next_offset=params.offset + params.limit if len(rows) > params.limit else None,
    )


@router.get("/cities")
def cities(
    db: DB,
    q: Annotated[str, Query(max_length=100)] = "",
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[dict[str, str]]:
    query = (
        visible()
        .with_only_columns(Store.country, Store.state, Store.city)
        .where(Store.city.icontains(q.strip(), autoescape=True))
        .distinct()
        .order_by(Store.country, Store.state, Store.city)
        .offset(offset)
        .limit(50)
    )
    return [
        {"country": country, "state": state, "city": city}
        for country, state, city in db.execute(query)
    ]


@router.get("/areas")
def areas(
    db: DB,
    city: Annotated[str, Query(min_length=2, max_length=100)],
    country: Annotated[str, Query(pattern="^[A-Z]{2}$")] = "IN",
    state: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[dict[str, str]]:
    query = (
        visible()
        .with_only_columns(Store.country, Store.state, Store.city, Store.area)
        .where(
            func.lower(Store.city) == city.strip().lower(),
            Store.country == country,
            Store.area != "",
        )
    )
    if state is not None:
        query = query.where(func.lower(Store.state) == state.strip().lower())
    rows = db.execute(
        query.distinct()
        .order_by(Store.country, Store.state, Store.city, Store.area)
        .offset(offset)
        .limit(50)
    )
    return [
        {"country": country, "state": region, "city": place, "area": area}
        for country, region, place, area in rows
    ]


@router.get("/places")
def places(
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> list[dict[str, object]]:
    term = q.strip()
    if len(term) < 2:
        raise AuthError(
            "PLACE_QUERY_REQUIRED", "Enter at least two characters of a city or area.", 422
        )
    query = (
        visible()
        .where(
            or_(
                Store.city.icontains(term, autoescape=True),
                Store.area.icontains(term, autoescape=True),
                Store.name.icontains(term, autoescape=True),
            )
        )
        .order_by(Store.country, Store.state, Store.city, Store.area, Store.name, Store.id)
        .offset(offset)
        .limit(20)
    )
    return [
        {
            "id": store.id,
            "label": ", ".join(filter(None, [store.area, store.city, store.state, store.country])),
            "reference_name": store.name,
            "latitude": store.latitude,
            "longitude": store.longitude,
        }
        for store, _ in db.execute(query)
    ]


@router.get("/stores/{store_id}", response_model=PublicStore)
def detail(store_id: UUID, db: DB) -> PublicStore:
    row = db.execute(visible().where(Store.id == store_id)).first()
    if row is None:
        raise AuthError("STORE_NOT_FOUND", "This store is not available for discovery.", 404)
    return public_store(row[0], row[1], datetime.now(UTC))
