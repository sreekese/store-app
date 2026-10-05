from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.profiles.schemas import Input, MerchantInput

Placement = Literal["BELOW_DAILY", "BELOW_OFFERS"]
Status = Literal["DRAFT", "ENABLED", "DISABLED", "ARCHIVED"]


class AdInput(Input):
    sponsor: str = Field(min_length=2, max_length=150)
    headline: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=3, max_length=500)
    image_url: str = Field(default="", max_length=2048)
    image_alt: str = Field(default="", max_length=150)
    cta: str = Field(min_length=2, max_length=60)
    placement: Placement
    destination_type: Literal["DISCOVER", "STORE", "OFFER"]
    store_id: UUID | None = None
    offer_id: UUID | None = None
    starts_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("image_url")
    @classmethod
    def safe_image(cls, value: str) -> str:
        normalized = MerchantInput.safe_link(value)
        if normalized and (not normalized.startswith("https://") or len(normalized) > 2048):
            raise ValueError("Creative images require a credential-free HTTPS URL")
        return normalized

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.expires_at <= self.starts_at:
            raise ValueError("End must follow start")
        if self.image_url and not self.image_alt:
            raise ValueError("Supply image alternative text")
        if self.destination_type == "DISCOVER" and (self.store_id or self.offer_id):
            raise ValueError("Discovery has no store or offer")
        if self.destination_type in {"STORE", "OFFER"} and not self.store_id:
            raise ValueError("Choose a branch")
        if (self.destination_type == "OFFER") != (self.offer_id is not None):
            raise ValueError("Choose an offer only for offer destinations")
        return self


class Revision(Input):
    revision: int = Field(ge=1)


class AdUpdate(AdInput):
    revision: int = Field(ge=1)


class Action(Revision):
    action: Literal["ENABLE", "DISABLE", "ARCHIVE"]
    preview_token: str = Field(default="", max_length=2000)
