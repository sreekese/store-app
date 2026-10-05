from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="review_rating"),
        CheckConstraint("status IN ('PENDING','PUBLISHED','HIDDEN')", name="review_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    redemption_id: Mapped[UUID] = mapped_column(
        ForeignKey("redemptions.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[UUID] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int]
    comment: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    revision: Mapped[int] = mapped_column(default=1)
    moderation_reason: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportCase(Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "target_type", "target_id", "reason", name="uq_report_target_reason"
        ),
        CheckConstraint(
            "status IN ('OPEN','UNDER_REVIEW','AWAITING_RESPONSE','RESOLVED')",
            name="support_status",
        ),
        CheckConstraint("target_type IN ('CLAIM','OFFER','STORE','REVIEW')", name="support_target"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reporter_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[UUID] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("coupon_claims.id", ondelete="CASCADE")
    )
    redemption_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("redemptions.id", ondelete="CASCADE")
    )
    target_type: Mapped[str] = mapped_column(String(10))
    target_id: Mapped[UUID]
    reason: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(2000))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    revision: Mapped[int] = mapped_column(default=1)
    resolution: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseAction(Base):
    __tablename__ = "support_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_cases.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_role: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
