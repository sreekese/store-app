from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("uq_category_name", func.lower(name), unique=True),)


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        ForeignKeyConstraint(["store_id", "merchant_id"], ["stores.id", "stores.merchant_id"]),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','PAUSED',"
            "'REJECTED','EXPIRED','ARCHIVED')",
            name="offer_status",
        ),
        CheckConstraint(
            "discount_type IN ('PERCENTAGE','FLAT_AMOUNT','BOGO','FREE_ITEM','SPECIAL_PRICE')",
            name="offer_discount_type",
        ),
        CheckConstraint(
            "customer_type IN ('ALL','NEW_CUSTOMERS','EXISTING_CUSTOMERS')",
            name="offer_customer_type",
        ),
        CheckConstraint("expires_at > starts_at", name="offer_dates"),
        CheckConstraint(
            "discount_value >= 0 AND minimum_purchase >= 0 "
            "AND (maximum_discount IS NULL OR maximum_discount > 0)",
            name="offer_money",
        ),
        CheckConstraint(
            "discount_type != 'PERCENTAGE' OR (discount_value > 0 AND discount_value <= 100)",
            name="offer_percentage",
        ),
        CheckConstraint("currency = 'INR'", name="offer_currency"),
        Index("ix_offers_status_dates", "status", "starts_at", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[UUID | None] = mapped_column(index=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(String(2000))
    image_url: Mapped[str] = mapped_column(String(2048), default="")
    discount_type: Mapped[str] = mapped_column(String(30))
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    minimum_purchase: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    maximum_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    customer_type: Mapped[str] = mapped_column(String(30), default="ALL")
    terms_conditions: Mapped[str] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    moderation_note: Mapped[str] = mapped_column(String(1000), default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(default=1)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
