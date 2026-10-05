from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: UUID
    store_ids: list[UUID] = Field(min_length=1, max_length=100)
    total_quantity: int = Field(ge=1, le=1000000)
    per_user_limit: int = Field(default=1, ge=1, le=100)
    validity_hours: int | None = Field(default=None, ge=1, le=8760)
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.starts_at >= self.expires_at or len(set(self.store_ids)) != len(self.store_ids):
            raise ValueError("Choose a valid period and distinct participating branches")
        return self


class CampaignUpdate(CampaignInput):
    revision: int = Field(ge=1)


class CampaignAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    action: Literal["ACTIVATE", "PAUSE", "CANCEL"]


class CampaignOutput(CampaignInput):
    id: UUID
    title: str
    status: str
    revision: int
    claimed_count: int
    available_count: int


class Receipt(BaseModel):
    id: UUID
    campaign_id: UUID
    title: str
    status: str
    claimed_at: datetime
    expires_at: datetime


class Allowance(BaseModel):
    period: str = "DAILY"
    limit: int = 1
    used: int
    remaining: int
    resets_at: datetime
    timezone: str = "Asia/Kolkata"
    policy_version: int = 1
