from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Advertisement(Base):
    __tablename__ = "advertisements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','ENABLED','DISABLED','ARCHIVED')", name="advertisement_status"
        ),
        CheckConstraint(
            "placement IN ('BELOW_DAILY','BELOW_OFFERS')", name="advertisement_placement"
        ),
        CheckConstraint(
            "destination_type IN ('DISCOVER','STORE','OFFER')", name="advertisement_destination"
        ),
        CheckConstraint("expires_at > starts_at", name="advertisement_dates"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sponsor: Mapped[str] = mapped_column(String(150))
    headline: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    image_url: Mapped[str] = mapped_column(String(2048), default="")
    image_alt: Mapped[str] = mapped_column(String(150), default="")
    cta: Mapped[str] = mapped_column(String(60))
    placement: Mapped[str] = mapped_column(String(20), index=True)
    destination_type: Mapped[str] = mapped_column(String(10))
    store_id: Mapped[UUID | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    offer_id: Mapped[UUID | None] = mapped_column(ForeignKey("offers.id", ondelete="SET NULL"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
