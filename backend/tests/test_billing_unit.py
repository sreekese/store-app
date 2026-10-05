import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.billing.provider import SandboxProvider
from app.billing.schemas import PlanInput
from app.core.config import Settings

SECRET = "sandbox-only-webhook-signing-secret-123456"


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 0},
        {"amount_minor": 1.5},
        {"amount_minor": True},
        {"period_days": 367},
        {"currency": "JPY"},
    ],
)
def test_plan_rejects_unsupported_prices_and_periods(changes):
    with pytest.raises(ValidationError):
        PlanInput.model_validate(
            dict(
                name="Test plan",
                description="Local test",
                currency="INR",
                amount_minor=100,
                period_days=30,
            )
            | changes
        )


def test_sandbox_cannot_start_in_production_or_without_secret():
    with pytest.raises(ValidationError):
        Settings(app_env="production", billing_provider="sandbox", billing_webhook_secret=SECRET)
    with pytest.raises(ValidationError):
        Settings(billing_provider="sandbox", billing_webhook_secret="")


def test_provider_idempotency_and_raw_body_signature():
    adapter = SandboxProvider(SECRET)
    reference = uuid4()
    assert adapter.create_order(reference, 100, "INR") == adapter.create_order(
        reference, 100, "INR"
    )
    assert adapter.refund(reference, "payment", 100, "INR") == adapter.refund(
        reference, "payment", 100, "INR"
    )
    raw = json.dumps(
        dict(
            id="event",
            kind="PAID",
            order_id="order",
            payment_id="payment",
            amount_minor=100,
            currency="INR",
        )
    ).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook(raw, signature).kind == "PAID"
    with pytest.raises(ValueError):
        adapter.verify_webhook(raw + b" ", signature)
    with pytest.raises(ValueError):
        adapter.verify_webhook(raw, "")
