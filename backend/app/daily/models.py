from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CouponPolicy(Base):
    __tablename__ = "coupon_policies"
    version: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DailyPick(Base):
    __tablename__ = "daily_picks"
    store_id: Mapped[UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True
    )
    business_date: Mapped[date] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("coupon_campaigns.id", ondelete="CASCADE")
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(default=1)


class Recommendation(Base):
    __tablename__ = "daily_recommendations"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    identity: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("coupon_campaigns.id", ondelete="CASCADE"))
    store_id: Mapped[UUID] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
