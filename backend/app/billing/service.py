import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.service import AuthError
from app.billing.models import BillingEvent, Payment, Plan, Refund
from app.billing.provider import ProviderEvent
from app.billing.schemas import PlanInput


def fail(message: str, status: int = 409) -> NoReturn:
    raise AuthError("BILLING_REQUEST_DENIED", message, status)


def plan_output(row: Plan) -> dict[str, Any]:
    return {
        "id": row.id,
        "revision": row.revision,
        **{key: getattr(row, key) for key in PlanInput.model_fields},
    }


def payment_output(row: Payment) -> dict[str, Any]:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "merchant_id",
            "plan_name",
            "merchant_name",
            "currency",
            "amount_minor",
            "period_days",
            "status",
            "created_at",
            "paid_at",
            "starts_at",
            "expires_at",
            "provider",
        )
    }


def lock_business(db: Session, merchant_id: UUID) -> None:
    # One lock order for checkout, webhook and refund paths; also serializes distinct events.
    db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(hashlib.sha256(merchant_id.bytes).digest()[:8], signed=True)},
    )


def apply_event(db: Session, event: ProviderEvent, body: bytes, provider: str) -> None:
    row = db.scalar(
        select(Payment).where(
            Payment.provider_order_id == event.order_id, Payment.provider == provider
        )
    )
    if row is None:
        fail("Unknown payment order.", 404)
    lock_business(db, row.merchant_id)
    db.refresh(row, with_for_update=True)
    # Event IDs are namespaced and serialized even if reused across different merchants.
    key = provider + ":" + event.id
    db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)},
    )
    digest = hashlib.sha256(body).hexdigest()
    previous = db.get(BillingEvent, key)
    if previous:
        if previous.payload_hash != digest or previous.payment_id != row.id:
            fail("Conflicting webhook event.")
        return
    if event.amount_minor != row.amount_minor or event.currency != row.currency:
        fail("Payment amount or currency does not match the saved order.")
    if row.provider_payment_id and row.provider_payment_id != event.payment_id:
        fail("Payment identifier does not match.")
    now = datetime.now(UTC)
    if event.kind == "PAID":
        if row.status == "PENDING":
            # Subscription periods are prepaid, with no automatic renewal or feature gating.
            end = db.scalar(
                select(Payment.expires_at)
                .where(
                    Payment.merchant_id == row.merchant_id,
                    Payment.status == "PAID",
                    Payment.expires_at > now,
                )
                .order_by(Payment.expires_at.desc())
                .limit(1)
            )
            row.status = "PAID"
            row.provider_payment_id = event.payment_id
            row.paid_at = now
            row.starts_at = end or now
            row.expires_at = row.starts_at + timedelta(days=row.period_days)
        # A late paid event must never resurrect a refunded payment.
    else:
        refund = db.scalar(select(Refund).where(Refund.payment_id == row.id).with_for_update())
        if row.status not in {"PAID", "REFUNDED"} or refund is None:
            fail("Payment or refund request is not ready; retry the event.")
        if refund.provider_refund_id != event.refund_id:
            fail("Refund identifier does not match.")
        row.status = "REFUNDED"
        refund.status = "COMPLETED"
        refund.completed_at = refund.completed_at or now
    db.add(BillingEvent(id=key, payment_id=row.id, kind=event.kind, payload_hash=digest))
    db.flush()
