from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.locations.spatial import LOCATION_SQL, GeographyPoint


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("location_preference IN ('MANUAL','GPS')", name="profile_location"),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    phone: Mapped[str] = mapped_column(String(30), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    area: Mapped[str] = mapped_column(String(100), default="")
    postal_code: Mapped[str] = mapped_column(String(20), default="")
    location_preference: Mapped[str] = mapped_column(String(10), default="MANUAL")


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','UNDER_REVIEW','VERIFIED','REJECTED','SUSPENDED')",
            name="merchant_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    business_name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(2000), default="")
    website: Mapped[str] = mapped_column(String(2048), default="")
    logo_url: Mapped[str] = mapped_column(String(2048), default="")
    cover_image_url: Mapped[str] = mapped_column(String(2048), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contact_email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    review_note: Mapped[str] = mapped_column(String(1000), default="")
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("id", "merchant_id", name="store_merchant_identity"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="store_status"),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="store_coordinate_pair"),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180",
            name="store_coordinate_bounds",
        ),
        Index("ix_stores_location", "location", postgresql_using="gist"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str] = mapped_column(String(500))
    city: Mapped[str] = mapped_column(String(100))
    area: Mapped[str] = mapped_column(String(100), server_default="")
    state: Mapped[str] = mapped_column(String(100), server_default="")
    country: Mapped[str] = mapped_column(String(2), server_default="IN")
    postal_code: Mapped[str] = mapped_column(String(20), server_default="")
    phone: Mapped[str] = mapped_column(String(30), server_default="")
    timezone: Mapped[str] = mapped_column(String(100), server_default="Asia/Kolkata")
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    location: Mapped[str | None] = mapped_column(
        GeographyPoint(), Computed(LOCATION_SQL, persisted=True)
    )
    status: Mapped[str] = mapped_column(String(10), server_default="ACTIVE")
    hours: Mapped[list[dict[str, object]]] = mapped_column(JSONB, server_default="[]")
    revision: Mapped[int] = mapped_column(server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffAssignment(Base):
    __tablename__ = "staff_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id", "merchant_id"], ["stores.id", "stores.merchant_id"], ondelete="CASCADE"
        ),
    )
    staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[UUID] = mapped_column(primary_key=True)
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )


class Invitation(Base):
    __tablename__ = "staff_invitations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    store_ids: Mapped[list[str]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    merchant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffAccess(Base):
    """Business roster and edit revision; branch assignments remain the access grant."""

    __tablename__ = "staff_access"
    merchant_id: Mapped[UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True
    )
    staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(server_default="1")
