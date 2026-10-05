from typing import Literal
from uuid import UUID

from pydantic import Field

from app.profiles.schemas import Input

CaseStatus = Literal["OPEN", "UNDER_REVIEW", "AWAITING_RESPONSE", "RESOLVED"]
ReviewStatus = Literal["PENDING", "PUBLISHED", "HIDDEN"]


class ReviewInput(Input):
    redemption_id: UUID
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str = Field(min_length=1, max_length=2000)


class Moderate(Input):
    revision: int = Field(ge=1)
    status: Literal["PUBLISHED", "HIDDEN"]
    reason: str = Field(min_length=1, max_length=1000)


class ReportInput(Input):
    target_type: Literal["CLAIM", "OFFER", "STORE", "REVIEW"]
    target_id: UUID
    store_id: UUID
    reason: Literal[
        "STORE_REFUSED_COUPON",
        "INVALID_OFFER",
        "MERCHANT_CLOSED",
        "INCORRECT_DISCOUNT",
        "FRAUDULENT_LISTING",
        "INAPPROPRIATE_CONTENT",
        "OTHER",
    ]
    description: str = Field(min_length=10, max_length=2000)


class Respond(Input):
    revision: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=2000)


class Transition(Respond):
    status: CaseStatus
