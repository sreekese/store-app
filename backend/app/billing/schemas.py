from typing import Literal
from uuid import UUID

from pydantic import Field

from app.profiles.schemas import Input


class PlanInput(Input):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=3, max_length=1000)
    currency: Literal["INR", "USD", "EUR", "GBP"]
    amount_minor: int = Field(strict=True, gt=0, le=100_000_000)
    period_days: int = Field(strict=True, ge=1, le=366)
    is_active: bool = False


class PlanUpdate(PlanInput):
    revision: int = Field(ge=1)


class OrderInput(Input):
    plan_id: UUID
    plan_revision: int = Field(ge=1)
    request_key: UUID


class RefundInput(Input):
    reason: str = Field(min_length=5, max_length=500)
