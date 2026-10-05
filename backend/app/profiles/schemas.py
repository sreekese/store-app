from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    TypeAdapter,
    computed_field,
    field_validator,
    model_validator,
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileInput(Input):
    display_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(default="", max_length=30, pattern=r"^[+0-9 ()-]*$")
    city: str = Field(default="", max_length=100)
    area: str = Field(default="", max_length=100)
    postal_code: str = Field(default="", max_length=20)
    location_preference: Literal["MANUAL", "GPS"] = "MANUAL"


class ProfileOutput(ProfileInput):
    email: str


class MerchantInput(Input):
    business_name: str = Field(min_length=2, max_length=150)
    category: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    website: str = Field(default="", max_length=2048)
    logo_url: str = Field(default="", max_length=2048)
    cover_image_url: str = Field(default="", max_length=2048)
    contact_email: EmailStr
    phone: str = Field(min_length=5, max_length=30, pattern=r"^[+0-9 ()-]+$")

    @field_validator("logo_url", "cover_image_url")
    @classmethod
    def secure_image(cls, value: str) -> str:
        if value and not value.startswith("https://"):
            raise ValueError("Images require HTTPS")
        return value

    @field_validator("website", "logo_url", "cover_image_url")
    @classmethod
    def safe_link(cls, value: str) -> str:
        if not value:
            return ""
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.username or url.password:
            raise ValueError("Business links must not contain credentials")
        return str(url)


class MerchantOutput(MerchantInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    review_note: str
    revision: int
    updated_at: datetime


class HoursInput(Input):
    day_of_week: int = Field(ge=0, le=6)
    is_closed: bool = False
    open_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    close_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    closes_next_day: bool = False

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.is_closed:
            if self.open_time is not None or self.close_time is not None or self.closes_next_day:
                raise ValueError("Closed days cannot contain hours")
        elif self.open_time is None or self.close_time is None:
            raise ValueError("Opening and closing times are required")
        elif self.closes_next_day:
            if self.close_time > self.open_time:
                raise ValueError("An opening period cannot exceed 24 hours")
        elif self.close_time <= self.open_time:
            raise ValueError(
                "Closing time must follow opening time; mark overnight when appropriate"
            )
        return self


class StoreInput(Input):
    name: str = Field(min_length=2, max_length=150)
    address: str = Field(min_length=3, max_length=500)
    city: str = Field(min_length=2, max_length=100)
    area: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=100)
    country: str = Field(default="IN", pattern=r"^[A-Z]{2}$")
    postal_code: str = Field(default="", max_length=20)
    phone: str = Field(default="", max_length=30, pattern=r"^[+0-9 ()-]*$")
    timezone: str = Field(default="Asia/Kolkata", max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    hours: list[HoursInput] = Field(default_factory=list, max_length=7)

    @field_validator("timezone")
    @classmethod
    def real_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA timezone, such as Asia/Kolkata") from None
        return value

    @model_validator(mode="after")
    def valid_location_and_week(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        if self.hours:
            if {h.day_of_week for h in self.hours} != set(range(7)):
                raise ValueError("Provide each weekday exactly once, Monday=0 through Sunday=6")
            intervals = []
            for h in self.hours:
                if not h.is_closed and h.open_time is not None and h.close_time is not None:
                    start = h.day_of_week * 1440 + minutes(h.open_time)
                    end = (
                        h.day_of_week * 1440
                        + minutes(h.close_time)
                        + (1440 if h.closes_next_day else 0)
                    )
                    intervals.append((start, end))
            # Repeat the first week to detect Sunday-to-Monday overlaps too.
            ordered = sorted(intervals + [(a + 10080, b + 10080) for a, b in intervals])
            if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
                raise ValueError("Opening periods cannot overlap the next day's hours")
        return self


def minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


class StoreUpdate(StoreInput):
    revision: int = Field(ge=1)


class StoreOutput(StoreInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    merchant_id: UUID
    revision: int
    updated_at: datetime


class AssignmentInput(Input):
    store_ids: list[UUID] = Field(max_length=50)

    @field_validator("store_ids")
    @classmethod
    def unique_stores(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("Stores must be unique")
        return values


class AssignmentUpdate(AssignmentInput):
    revision: int = Field(ge=1)


class InviteInput(AssignmentInput):
    email: EmailStr
    store_ids: list[UUID] = Field(min_length=1, max_length=50)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.lower()


class InviteToken(Input):
    token: str = Field(min_length=40, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class AcceptInput(InviteToken):
    display_name: str = Field(min_length=1, max_length=100)
    # Password whitespace is significant, unlike business/profile text.
    password: str = Field(min_length=12, max_length=128)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    @field_validator("display_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class ReviewInput(Input):
    status: Literal["UNDER_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED"]
    note: str = Field(default="", max_length=1000)
    revision: int = Field(ge=1)


class InvitationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    store_ids: list[str]
    expires_at: datetime
    closed_at: datetime | None
    accepted_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        if self.accepted_at:
            return "ACCEPTED"
        if self.closed_at:
            return "CANCELLED"
        return "EXPIRED" if self.expires_at <= datetime.now(UTC) else "PENDING"


class StaffOutput(BaseModel):
    revision: int
    account_active: bool
    id: UUID
    email: str
    display_name: str
    store_ids: list[UUID]
