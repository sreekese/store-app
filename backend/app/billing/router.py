from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import DB, csrf, require_roles
from app.auth.models import Role, User
from app.billing.models import Payment, Plan, Refund
from app.billing.provider import PaymentProvider, SandboxProvider
from app.billing.schemas import OrderInput, PlanInput, PlanUpdate, RefundInput
from app.billing.service import apply_event, fail, lock_business, payment_output, plan_output
from app.offers.service import record
from app.profiles.models import Merchant

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"], dependencies=[Depends(csrf)])
webhooks = APIRouter(prefix="/api/v1/billing", tags=["Billing webhooks"])
Super = Annotated[User, Depends(require_roles(Role.SUPER_ADMIN))]
Owner = Annotated[User, Depends(require_roles(Role.MERCHANT))]
BillingUser = Annotated[User, Depends(require_roles(Role.MERCHANT, Role.SUPER_ADMIN))]
Offset = Annotated[int, Query(ge=0, le=10000)]


def provider(request: Request) -> PaymentProvider:
    settings = request.app.state.settings
    if settings.billing_provider != "sandbox" or settings.app_env not in {"development", "test"}:
        fail("Payments are not configured.", 503)
    secret = settings.billing_webhook_secret.get_secret_value()
    if len(secret) < 32:
        fail("Payments are not configured.", 503)
    return SandboxProvider(secret)


def merchant(db: DB, user: User) -> Merchant:
    row = db.scalar(select(Merchant).where(Merchant.owner_id == user.id))
    if row is None:
        fail("Complete your business profile first.", 404)
    return row


def payment(db: DB, user: User, id: UUID) -> Payment:
    row = db.get(Payment, id)
    if row is None or (user.role != Role.SUPER_ADMIN and row.merchant_id != merchant(db, user).id):
        fail("Payment not found.", 404)
    return row


@router.get("/config")
def config(request: Request, user: BillingUser) -> dict[str, Any]:
    settings = request.app.state.settings
    enabled = (
        settings.billing_provider == "sandbox"
        and settings.app_env in {"development", "test"}
        and len(settings.billing_webhook_secret.get_secret_value()) >= 32
    )
    return {
        "provider": "sandbox" if enabled else "disabled",
        "enabled": enabled,
        "automatic_renewal": False,
    }


@router.get("/plans")
def plans(db: DB, user: BillingUser, offset: Offset = 0) -> dict[str, Any]:
    query = select(Plan)
    if user.role != Role.SUPER_ADMIN:
        query = query.where(Plan.is_active.is_(True))
    rows = list(
        db.scalars(query.order_by(Plan.created_at.desc(), Plan.id).offset(offset).limit(21))
    )
    return {
        "items": [plan_output(r) for r in rows[:20]],
        "next_offset": offset + 20 if len(rows) > 20 and offset < 10000 else None,
    }


@router.post("/plans", status_code=201)
def create_plan(data: PlanInput, db: DB, user: Super) -> dict[str, Any]:
    row = Plan(**data.model_dump())
    db.add(row)
    db.flush()
    record(db, user, None, "BILLING_PLAN_CREATED", plan_id=str(row.id), **data.model_dump())
    db.commit()
    return plan_output(row)


@router.put("/plans/{id}")
def update_plan(id: UUID, data: PlanUpdate, db: DB, user: Super) -> dict[str, Any]:
    row = db.scalar(select(Plan).where(Plan.id == id).with_for_update())
    if row is None:
        fail("Plan not found.", 404)
    if row.revision != data.revision:
        fail("This plan changed. Refresh before saving.")
    for key, value in data.model_dump(exclude={"revision"}).items():
        setattr(row, key, value)
    row.revision += 1
    record(db, user, None, "BILLING_PLAN_UPDATED", plan_id=str(row.id), **data.model_dump())
    db.commit()
    return plan_output(row)


@router.post("/orders", status_code=201)
def create_order(data: OrderInput, db: DB, user: Owner, request: Request) -> dict[str, Any]:
    adapter = provider(request)
    business = merchant(db, user)
    lock_business(db, business.id)
    db.refresh(business)
    if business.status != "VERIFIED":
        fail("Only verified businesses can create payment orders.", 403)
    key = str(business.id) + ":" + str(data.request_key)
    row = db.scalar(select(Payment).where(Payment.request_key == key))
    if row:
        if row.plan_id != data.plan_id:
            fail("This request key belongs to a different plan.")
    else:
        plan = db.scalar(select(Plan).where(Plan.id == data.plan_id).with_for_update())
        if plan is None or not plan.is_active or plan.revision != data.plan_revision:
            fail("This plan is unavailable or changed. Review the current plans.")
        # Reuse an unpaid checkout rather than creating accidental duplicate purchases.
        if db.scalar(
            select(Payment.id).where(
                Payment.merchant_id == business.id, Payment.status == "PENDING"
            )
        ):
            fail("An unpaid order already exists. Use its details before creating another.")
        row = Payment(
            merchant_id=business.id,
            plan_id=plan.id,
            request_key=key,
            provider=adapter.name,
            plan_name=plan.name,
            merchant_name=business.business_name,
            currency=plan.currency,
            amount_minor=plan.amount_minor,
            period_days=plan.period_days,
        )
        db.add(row)
        db.flush()
        record(db, user, business.id, "BILLING_ORDER_CREATED", payment_id=str(row.id))
        # Persist before provider I/O. Same request key recovers interrupted attempts.
        db.commit()
        lock_business(db, business.id)
        db.refresh(row, with_for_update=True)
    if row.provider_order_id is None:
        result = adapter.create_order(row.id, row.amount_minor, row.currency)
        row.provider_order_id = result.id
    db.commit()
    return payment_output(row)


@router.get("/payments")
def payments(db: DB, user: BillingUser, offset: Offset = 0) -> dict[str, Any]:
    query = select(Payment)
    if user.role != Role.SUPER_ADMIN:
        query = query.where(Payment.merchant_id == merchant(db, user).id)
    rows = list(
        db.scalars(query.order_by(Payment.created_at.desc(), Payment.id).offset(offset).limit(21))
    )
    return {
        "items": [payment_output(r) for r in rows[:20]],
        "next_offset": offset + 20 if len(rows) > 20 and offset < 10000 else None,
    }


@router.get("/subscription")
def subscription(db: DB, user: Owner) -> dict[str, Any]:
    now = datetime.now(UTC)
    row = db.scalar(
        select(Payment)
        .where(
            Payment.merchant_id == merchant(db, user).id,
            Payment.status == "PAID",
            Payment.starts_at <= now,
            Payment.expires_at > now,
        )
        .order_by(Payment.expires_at.desc())
        .limit(1)
    )
    return {
        "status": "ACTIVE" if row else "INACTIVE",
        "payment": payment_output(row) if row else None,
        "automatic_renewal": False,
        "server_time": now,
    }


@router.get("/payments/{id}/invoice")
def invoice(id: UUID, db: DB, user: BillingUser) -> dict[str, Any]:
    row = payment(db, user, id)
    if row.paid_at is None:
        fail("An invoice is available only after a verified successful payment.")
    return {
        "number": "SANDBOX-" + row.id.hex.upper(),
        "kind": "SANDBOX_INVOICE",
        "issued_at": row.paid_at,
        "tax_invoice": False,
        "payment": payment_output(row),
    }


@router.post("/payments/{id}/refund")
def refund(id: UUID, data: RefundInput, db: DB, user: Super, request: Request) -> dict[str, Any]:
    adapter = provider(request)
    row = payment(db, user, id)
    lock_business(db, row.merchant_id)
    db.refresh(row, with_for_update=True)
    existing = db.scalar(select(Refund).where(Refund.payment_id == row.id))
    if existing is None:
        if row.status != "PAID" or row.provider_payment_id is None:
            fail("Only confirmed payments can be refunded.")
        existing = Refund(payment_id=row.id, reason=data.reason)
        db.add(existing)
        db.flush()
        record(
            db,
            user,
            row.merchant_id,
            "BILLING_REFUND_REQUESTED",
            payment_id=str(row.id),
            reason=data.reason,
        )
        db.commit()
        lock_business(db, row.merchant_id)
        db.refresh(existing, with_for_update=True)
    if existing.provider_refund_id is None:
        if row.provider_payment_id is None:
            fail("Payment confirmation is missing.")
        existing.provider_refund_id = adapter.refund(
            existing.id, row.provider_payment_id, row.amount_minor, row.currency
        )
    db.commit()
    return {"id": existing.id, "status": existing.status, "reason": existing.reason}


@webhooks.post("/webhooks/sandbox")
async def webhook(request: Request, db: DB) -> dict[str, bool]:
    adapter = provider(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            fail("Webhook is too large.", 413)
    signature = request.headers.get("x-billing-signature", "")
    try:
        event = adapter.verify_webhook(bytes(body), signature)
    except (ValueError, TypeError, UnicodeError):
        fail("Invalid webhook.", 400)
    try:
        apply_event(db, event, bytes(body), adapter.name)
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("Conflicting payment identifiers.")
    return {"received": True}
