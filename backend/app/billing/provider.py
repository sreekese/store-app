"""Adapters normalize provider events only after authenticating the raw webhook body."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True)
class ProviderOrder:
    id: str
    checkout_url: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    id: str
    kind: Literal["PAID", "REFUNDED"]
    order_id: str
    payment_id: str
    amount_minor: int
    currency: str
    refund_id: str | None = None


class PaymentProvider(Protocol):
    name: str

    def create_order(self, reference: UUID, amount_minor: int, currency: str) -> ProviderOrder:
        """Retries for a reference must return the same order without charging twice."""
        ...

    def verify_webhook(self, body: bytes, signature: str) -> ProviderEvent:
        """Reject unsigned, malformed or unsupported events before returning."""
        ...

    def refund(self, reference: UUID, payment_id: str, amount_minor: int, currency: str) -> str:
        """Request a full refund idempotently; webhook confirms completion."""
        ...


class SandboxProvider:
    """Local deterministic adapter. Never connects to a payment network."""

    name = "sandbox"

    def __init__(self, secret: str):
        if len(secret) < 32:
            raise ValueError("A private webhook secret of at least 32 characters is required")
        self.secret = secret

    def create_order(self, reference: UUID, amount_minor: int, currency: str) -> ProviderOrder:
        return ProviderOrder("sandbox_order_" + reference.hex)

    def refund(self, reference: UUID, payment_id: str, amount_minor: int, currency: str) -> str:
        return "sandbox_refund_" + reference.hex

    def verify_webhook(self, body: bytes, signature: str) -> ProviderEvent:
        import hashlib
        import hmac
        import json

        from pydantic import BaseModel, ConfigDict, Field

        class EventInput(BaseModel):
            model_config = ConfigDict(extra="forbid", strict=True)
            id: str = Field(min_length=1, max_length=150)
            kind: Literal["PAID", "REFUNDED"]
            order_id: str = Field(min_length=1, max_length=200)
            payment_id: str = Field(min_length=1, max_length=200)
            amount_minor: int = Field(gt=0)
            currency: str = Field(pattern=r"^[A-Z]{3}$")
            refund_id: str | None = Field(default=None, max_length=200)

        expected = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid webhook signature")
        event = EventInput.model_validate(json.loads(body))
        if (event.kind == "REFUNDED") != (event.refund_id is not None):
            raise ValueError("Invalid refund event")
        return ProviderEvent(**event.model_dump())
