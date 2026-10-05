"""Provider-independent billing records; monetary amounts use integer minor units."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Plan(Base):
    __tablename__ = "billing_plans"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="billing_plan_amount"),
        CheckConstraint("period_days BETWEEN 1 AND 366", name="billing_plan_period"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000))
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int]
    period_days: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "billing_payments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="billing_payment_amount"),
        CheckConstraint("status IN ('PENDING','PAID','REFUNDED')", name="billing_payment_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    merchant_id: Mapped[UUID] = mapped_column(ForeignKey("merchants.id"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("billing_plans.id"))
    request_key: Mapped[str] = mapped_column(String(200), unique=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_order_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    plan_name: Mapped[str] = mapped_column(String(100))
    merchant_name: Mapped[str] = mapped_column(String(150))
    currency: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int]
    period_days: Mapped[int]
    status: Mapped[str] = mapped_column(String(15), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("billing_payments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Refund(Base):
    __tablename__ = "billing_refunds"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("billing_payments.id"), unique=True)
    provider_refund_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
