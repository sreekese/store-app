from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.profiles.schemas import Input, MerchantInput


class CategoryInput(Input):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    is_active: bool = True


class CategoryUpdate(CategoryInput):
    revision: int = Field(ge=1)


class CategoryOutput(CategoryInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    revision: int


class OfferInput(Input):
    category_id: UUID
    store_id: UUID | None = None
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=3, max_length=2000)
    image_url: str = Field(default="", max_length=2048)
    discount_type: Literal["PERCENTAGE", "FLAT_AMOUNT", "BOGO", "FREE_ITEM", "SPECIAL_PRICE"]
    discount_value: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    minimum_purchase: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    maximum_discount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: Literal["INR"] = "INR"
    customer_type: Literal["ALL", "NEW_CUSTOMERS", "EXISTING_CUSTOMERS"] = "ALL"
    terms_conditions: str = Field(min_length=3, max_length=4000)
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("image_url")
    @classmethod
    def safe_image(cls, value: str) -> str:
        normalized = MerchantInput.safe_link(value)
        if len(normalized) > 2048:
            raise ValueError("Image URL is too long")
        return normalized

    @model_validator(mode="after")
    def compatible_rules(self) -> Self:
        if self.expires_at <= self.starts_at:
            raise ValueError("Expiry must be later than the start")
        if self.discount_type == "PERCENTAGE" and not 0 < self.discount_value <= 100:
            raise ValueError("Percentage must be greater than zero and at most 100")
        if self.discount_type in {"FLAT_AMOUNT", "SPECIAL_PRICE"} and self.discount_value <= 0:
            raise ValueError("Amount must be greater than zero")
        if self.discount_type in {"BOGO", "FREE_ITEM"} and self.discount_value != 0:
            raise ValueError("BOGO/free item details belong in the terms, not a numeric discount")
        if self.maximum_discount is not None and self.discount_type != "PERCENTAGE":
            raise ValueError("Only percentage discounts accept a maximum discount cap")
        if self.discount_type == "FLAT_AMOUNT" and self.minimum_purchase < self.discount_value:
            raise ValueError("The minimum purchase must cover the flat discount")
        return self


class OfferUpdate(OfferInput):
    revision: int = Field(ge=1)


class OfferOutput(OfferInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    merchant_id: UUID
    status: str
    moderation_note: str
    approved: bool
    admin_hold: bool
    revision: int
    updated_at: datetime


class AdminOfferOutput(OfferOutput):
    business_name: str
    category_name: str
    store_name: str | None


class Action(Input):
    revision: int = Field(ge=1)
    action: Literal["SUBMIT", "PAUSE", "ARCHIVE"]


class Review(Input):
    revision: int = Field(ge=1)
    action: Literal["APPROVE", "REJECT", "SUSPEND", "REACTIVATE"]
    note: str = Field(default="", max_length=1000)


class PublicOffer(OfferInput):
    id: UUID
    business_name: str
    category_name: str
    store_name: str
    matched_store_id: UUID
    city: str
    area: str
    latitude: float
    longitude: float
    distance_meters: float | None = None


class PublicPage(BaseModel):
    offers: list[PublicOffer]
    next_offset: int | None
    radius_km: float | None = None
