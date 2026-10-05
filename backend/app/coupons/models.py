from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Campaign(Base):
    __tablename__ = "coupon_campaigns"
    __table_args__ = (
        CheckConstraint(
            "total_quantity > 0 AND claimed_count >= 0 AND claimed_count <= total_quantity",
            name="campaign_stock",
        ),
        CheckConstraint("per_user_limit > 0", name="campaign_user_limit"),
        CheckConstraint("expires_at > starts_at", name="campaign_dates"),
        CheckConstraint("validity_hours IS NULL OR validity_hours > 0", name="campaign_validity"),
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','CANCELLED')", name="campaign_status"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    offer_id: Mapped[UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    total_quantity: Mapped[int]
    claimed_count: Mapped[int] = mapped_column(default=0)
    per_user_limit: Mapped[int] = mapped_column(default=1)
    validity_hours: Mapped[int | None]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignBranch(Base):
    __tablename__ = "coupon_campaign_branches"
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("coupon_campaigns.id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True
    )


class AllowanceUsage(Base):
    __tablename__ = "coupon_allowance_usage"
    __table_args__ = (CheckConstraint("used >= 0", name="allowance_used"),)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[int] = mapped_column(default=0)
    policy_version: Mapped[int] = mapped_column(default=1)


class CouponClaim(Base):
    __tablename__ = "coupon_claims"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_claim_user_request"),
        CheckConstraint(
            "status IN ('CLAIMED','REDEEMED','EXPIRED','CANCELLED')", name="claim_status"
        ),
        CheckConstraint("expires_at > claimed_at", name="claim_dates"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("coupon_campaigns.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[UUID]
    claim_token: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="CLAIMED")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
