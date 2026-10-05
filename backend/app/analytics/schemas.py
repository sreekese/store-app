from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.profiles.schemas import Input


class EventInput(Input):
    kind: Literal["OFFER_VIEWED", "STORE_VIEWED", "COUPON_VIEWED", "AD_VIEWED", "AD_CLICKED"]
    target_id: UUID


class Filters(Input):
    kind: Literal["daily", "campaigns", "merchants", "events", "revenue"] = "daily"
    start_date: date
    end_date: date
    merchant_id: UUID | None = None
    campaign_offset: int = Field(default=0, ge=0, le=10000)
    merchant_offset: int = Field(default=0, ge=0, le=10000)
