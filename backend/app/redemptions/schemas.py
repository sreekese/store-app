from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.offers.schemas import OfferInput


class ValidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    store_id: UUID
    claim_token: str = Field(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    purchase_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    reward_value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class RedeemInput(ValidateInput):
    confirmation_token: str = Field(min_length=20, max_length=2000)
    terms_confirmed: Literal[True]


class Preview(BaseModel):
    claim_id: UUID
    title: str
    business_name: str
    store_name: str
    expires_at: datetime
    offer: OfferInput
    purchase_amount: Decimal
    discount_amount: Decimal
    payable_amount: Decimal
    confirmation_token: str
    confirm_before: datetime


class Receipt(BaseModel):
    id: UUID
    claim_id: UUID
    store_id: UUID
    actor_id: UUID | None
    title: str
    business_name: str
    store_name: str
    redeemed_at: datetime
    purchase_amount: Decimal
    discount_amount: Decimal
    payable_amount: Decimal
    currency: str = "INR"
