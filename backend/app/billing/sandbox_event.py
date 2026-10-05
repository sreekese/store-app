"""Local/test webhook sender. It never contacts a payment network or collects money."""

import argparse
import hashlib
import hmac
import json
from http.client import HTTPConnection
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import Payment, Refund
from app.core.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payment_id", type=UUID)
    parser.add_argument("kind", choices=["PAID", "REFUNDED"])
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in {"development", "test"} or settings.billing_provider != "sandbox":
        parser.error("Sandbox billing must be explicitly enabled in a local/test environment")
    parsed = urlparse(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Only a loopback HTTP address is allowed")
    app = create_app(settings)
    with Session(app.state.engine) as db:
        row = db.get(Payment, args.payment_id)
        if row is None or row.provider != "sandbox" or not row.provider_order_id:
            parser.error("Sandbox order not found")
        payload = {
            "id": f"sandbox_{row.id.hex}_{args.kind}",
            "kind": args.kind,
            "order_id": row.provider_order_id,
            "payment_id": row.provider_payment_id or "sandbox_payment_" + row.id.hex,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
        }
        if args.kind == "REFUNDED":
            refund = db.scalar(select(Refund).where(Refund.payment_id == row.id))
            if refund is None or not refund.provider_refund_id:
                parser.error("Request a refund from the superadmin dashboard first")
            payload["refund_id"] = refund.provider_refund_id
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        settings.billing_webhook_secret.get_secret_value().encode(), raw, hashlib.sha256
    ).hexdigest()
    connection = HTTPConnection(parsed.hostname, parsed.port or 80, timeout=10)
    try:
        connection.request(
            "POST",
            "/api/v1/billing/webhooks/sandbox",
            body=raw,
            headers={"Content-Type": "application/json", "X-Billing-Signature": signature},
        )
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise RuntimeError(f"Sandbox webhook rejected: {response.status}")
        print(f"Sandbox webhook accepted: {response.status}")
    finally:
        connection.close()
    app.state.engine.dispose()


if __name__ == "__main__":
    main()
