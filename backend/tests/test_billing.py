import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_locations import located

from app.auth.models import Role
from app.billing.models import BillingEvent, Payment, Refund

pytestmark = pytest.mark.integration
BASE = "/api/v1/billing"
SECRET = "sandbox-test-webhook-secret-for-tests-only-123456"


def setup(client):
    client.app.state.settings.billing_provider = "sandbox"
    client.app.state.settings.billing_webhook_secret = SecretStr(SECRET)
    owner, business, _ = located(client)
    admin = bearer(login(client, create_user(client, Role.SUPER_ADMIN)))
    r = client.post(BASE + "/plans", headers=admin, json=plan_fields())
    assert r.status_code == 201, r.text
    return owner, admin, business, r.json()


def plan_fields(**changes):
    return (
        dict(
            name="Test plan",
            description="Sandbox subscription",
            currency="INR",
            amount_minor=12000,
            period_days=30,
            is_active=True,
        )
        | changes
    )


def order(client, owner, plan, key=None):
    return client.post(
        BASE + "/orders",
        headers=owner,
        json={
            "plan_id": plan["id"],
            "plan_revision": plan["revision"],
            "request_key": str(key or uuid4()),
        },
    )


def event(client, payment, **changes):
    with Session(client.app.state.engine) as db:
        row = db.get(Payment, UUID(payment["id"]))
        body = (
            dict(
                id="event_" + uuid4().hex,
                kind="PAID",
                order_id=row.provider_order_id,
                payment_id="payment_" + row.id.hex,
                amount_minor=row.amount_minor,
                currency=row.currency,
            )
            | changes
        )
    return body


def deliver(client, body, signature=None):
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = (
        signature
        if signature is not None
        else hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    )
    return client.post(
        BASE + "/webhooks/sandbox",
        content=raw,
        headers={"X-Billing-Signature": signature, "Content-Type": "application/json"},
    )


def test_order_webhook_subscription_and_invoice(client):
    owner, admin, _, plan = setup(client)
    key = uuid4()
    r = order(client, owner, plan, key)
    assert r.status_code == 201, r.text
    payment = r.json()
    assert payment["status"] == "PENDING"
    assert order(client, owner, plan, key).json()["id"] == payment["id"]
    assert order(client, owner, plan).status_code == 409
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "INACTIVE"
    assert client.get(f"{BASE}/payments/{payment['id']}/invoice", headers=owner).status_code == 409
    assert deliver(client, event(client, payment), "forged").status_code == 400
    body = event(client, payment)
    assert deliver(client, body).status_code == 200
    assert deliver(client, body).status_code == 200
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "ACTIVE"
    invoice = client.get(f"{BASE}/payments/{payment['id']}/invoice", headers=owner).json()
    assert invoice["payment"]["amount_minor"] == 12000 and invoice["tax_invoice"] is False
    assert invoice["number"].startswith("SANDBOX-")
    assert "provider_payment_id" not in invoice["payment"]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(BillingEvent)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": 1},
        {"currency": "USD"},
        {"order_id": "unknown"},
        {"amount_minor": True},
        {"kind": "SUCCESS"},
    ],
)
def test_webhook_mismatch_never_activates(client, changes):
    owner, _, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    assert deliver(client, event(client, payment, **changes)).status_code in {400, 404, 409}
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "INACTIVE"


def test_plan_revision_and_snapshot(client):
    owner, admin, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    r = client.put(
        f"{BASE}/plans/{plan['id']}",
        headers=admin,
        json=plan_fields(amount_minor=50000, revision=plan["revision"], is_active=False),
    )
    assert r.status_code == 200
    assert (
        client.put(
            f"{BASE}/plans/{plan['id']}", headers=admin, json=plan_fields(revision=1)
        ).status_code
        == 409
    )
    assert client.get(BASE + "/plans", headers=owner).json()["items"] == []
    assert deliver(client, event(client, payment)).status_code == 200
    invoice = client.get(f"{BASE}/payments/{payment['id']}/invoice", headers=owner).json()
    assert invoice["payment"]["amount_minor"] == 12000
    assert order(client, owner, plan).status_code == 409


@pytest.mark.parametrize("role", [Role.USER, Role.ADMIN, Role.MERCHANT_STAFF])
def test_billing_role_restrictions(client, role):
    headers = bearer(login(client, create_user(client, role)))
    for path in ["/plans", "/payments", "/config", "/subscription", f"/payments/{uuid4()}/invoice"]:
        assert client.get(BASE + path, headers=headers).status_code == 403
    assert client.post(BASE + "/plans", headers=headers, json=plan_fields()).status_code == 403


def test_merchant_cannot_manage_plans_refund_or_read_other_business(client):
    owner, _, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    other, _, _ = located(client)
    assert client.get(BASE + "/payments", headers=other).json()["items"] == []
    assert client.get(f"{BASE}/payments/{payment['id']}/invoice", headers=other).status_code == 404
    assert client.post(BASE + "/plans", headers=owner, json=plan_fields()).status_code == 403
    assert (
        client.post(
            f"{BASE}/payments/{payment['id']}/refund",
            headers=owner,
            json={"reason": "Testing refund"},
        ).status_code
        == 403
    )


def test_refund_requires_confirmation_and_late_payment_does_not_resurrect(client):
    owner, admin, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    paid = event(client, payment)
    assert deliver(client, paid).status_code == 200
    r = client.post(
        f"{BASE}/payments/{payment['id']}/refund",
        headers=admin,
        json={"reason": "Test full refund"},
    )
    assert r.status_code == 200 and r.json()["status"] == "REQUESTED"
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "ACTIVE"
    with Session(client.app.state.engine) as db:
        refund_id = db.scalar(select(Refund.provider_refund_id))
    refunded = event(client, payment, kind="REFUNDED", refund_id=refund_id)
    assert deliver(client, refunded).status_code == 200
    assert deliver(client, refunded).status_code == 200
    assert deliver(client, event(client, payment)).status_code == 200
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "INACTIVE"
    assert client.get(BASE + "/payments", headers=owner).json()["items"][0]["status"] == "REFUNDED"
    assert (
        client.post(
            f"{BASE}/payments/{payment['id']}/refund",
            headers=admin,
            json={"reason": "Repeat request"},
        ).json()["id"]
        == r.json()["id"]
    )


def test_concurrent_duplicate_orders_and_events(client):
    owner, _, _, plan = setup(client)
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: order(client, owner, plan, key), range(2)))
    assert all(r.status_code == 201 for r in results)
    assert results[0].json()["id"] == results[1].json()["id"]
    payment = results[0].json()
    body = event(client, payment)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliver(client, body), range(2)))
    assert all(r.status_code == 200 for r in results)
    assert deliver(client, {**body, "amount_minor": 1}).status_code == 409
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 1
        assert db.scalar(select(func.count()).select_from(BillingEvent)) == 1
        row = db.get(Payment, UUID(payment["id"]))
        assert row.expires_at - row.starts_at == timedelta(days=30)


def test_expired_subscription_is_inactive(client):
    owner, _, _, plan = setup(client)
    payment = order(client, owner, plan).json()
    assert deliver(client, event(client, payment)).status_code == 200
    with Session(client.app.state.engine) as db:
        row = db.get(Payment, UUID(payment["id"]))
        row.starts_at = datetime.now(UTC) - timedelta(days=31)
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    assert client.get(BASE + "/subscription", headers=owner).json()["status"] == "INACTIVE"


def test_disabled_checkout_and_missing_signature(client):
    owner, _, _, plan = setup(client)
    client.app.state.settings.billing_provider = "disabled"
    assert order(client, owner, plan).status_code == 503
    assert client.get(BASE + "/config", headers=owner).json()["enabled"] is False
