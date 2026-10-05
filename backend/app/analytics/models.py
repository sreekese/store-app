from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "target_id", "bucket", name="analytics_event_dedup"),
        CheckConstraint(
            "kind IN ('OFFER_VIEWED','STORE_VIEWED','COUPON_VIEWED','AD_VIEWED','AD_CLICKED')",
            name="analytics_event_kind",
        ),
        Index("ix_analytics_scope_time", "merchant_id", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    merchant_id: Mapped[UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[UUID]
    bucket: Mapped[int]
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
