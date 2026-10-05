from datetime import UTC, datetime, timedelta
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.daily.models import CouponPolicy


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowance: int = Field(default=1, ge=1, le=100)
    period: Literal["DAILY", "WEEKLY"] = "DAILY"
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=100)
    default_radius_km: float = Field(default=5, ge=0.1, le=100, allow_inf_nan=False)
    max_radius_km: float = Field(default=10, ge=0.1, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose an IANA timezone") from exc
        if self.default_radius_km > self.max_radius_km:
            raise ValueError("Default radius exceeds maximum")
        return self


class Schedule(Rules):
    effective_at: AwareDatetime
    current_version: int = Field(ge=1)


def active(db: Session, now: datetime) -> CouponPolicy:
    row = db.scalar(
        select(CouponPolicy)
        .where(CouponPolicy.effective_at <= now)
        .order_by(CouponPolicy.effective_at.desc())
        .limit(1)
    )
    if not (row is not None):
        raise RuntimeError("Required application state is unavailable")
    return row


def window(policy: CouponPolicy, now: datetime) -> tuple[datetime, datetime]:
    rules = Rules.model_validate(policy.rules)
    start = now.astimezone(ZoneInfo(rules.timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if rules.period == "WEEKLY":
        start -= timedelta(days=start.weekday())
    end = start + timedelta(days=7 if rules.period == "WEEKLY" else 1)
    # A timezone/period change must never count time before its activation twice.
    return max(start.astimezone(UTC), policy.effective_at), end.astimezone(UTC)
