from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_auth import bearer, create_user, login
from test_daily import fixture, search
from test_redemptions import confirm, preview, setup_coupon

from app.auth.models import Role
from app.coupons.models import CouponClaim
from app.coupons.service import claim_event
from app.jobs.models import Job
from app.jobs.service import process_one
from app.jobs.worker import handlers
from app.notifications.events import (
    daily_notification,
    expiry_reminder,
    schedule_daily,
)
from app.notifications.models import CapturedEmail, Notification, NotificationPreference
from app.notifications.service import email_delivery, notify
from app.redemptions.service import redeemed_event

pytestmark = pytest.mark.integration

HANDLERS = handlers()


def drain(client):
    for _ in range(15):
        if not process_one(client.app.state.engine, HANDLERS):
            return
    raise AssertionError("Unexpected unbounded work")


def test_claim_and_redemption_create_notifications_only_in_worker(client):
    owner, headers, _, _, _, claimed, data = setup_coupon(client)
    assert client.get("/api/v1/notifications", headers=headers).json()["items"] == []
    result = confirm(client, owner, data, preview(client, owner, data).json())
    assert result.status_code == 200
    assert client.get("/api/v1/notifications", headers=headers).json()["items"] == []
    drain(client)
    inbox = client.get("/api/v1/notifications", headers=headers)
    assert inbox.status_code == 200 and inbox.headers["cache-control"] == "no-store"
    assert {n["kind"] for n in inbox.json()["items"]} == {"COUPON_CLAIMED", "COUPON_REDEEMED"}
    assert data["claim_token"] not in inbox.text
    assert (
        client.get("/api/v1/shopper/wallet/" + claimed["id"], headers=headers).json()["status"]
        == "REDEEMED"
    )
    with Session(client.app.state.engine) as db:
        claim_event(db, {"claim_id": claimed["id"]})
        redeemed_event(db, {"redemption_id": result.json()["id"]})
        db.commit()
    assert len(client.get("/api/v1/notifications", headers=headers).json()["items"]) == 2


def test_own_inbox_read_filters_pagination_and_preference_scope(client):
    user = create_user(client)
    headers = bearer(login(client, user))
    other = bearer(login(client, create_user(client)))
    with Session(client.app.state.engine) as db:
        for n in range(23):
            notify(
                db,
                user_id=user.id,
                key=f"event:{n}",
                kind="TEST",
                title="Update",
                body="Safe message",
                link="/app",
            )
        db.commit()
    page = client.get("/api/v1/notifications", headers=headers).json()
    assert page["unread_count"] == 23 and len(page["items"]) == 20 and page["next_offset"] == 20
    id = page["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{id}/read", headers=other).status_code == 404
    assert client.get("/api/v1/notifications", headers=other).json()["items"] == []
    assert client.post(f"/api/v1/notifications/{id}/read", headers=headers).status_code == 200
    assert client.post(f"/api/v1/notifications/{id}/read", headers=headers).status_code == 200
    assert (
        client.get("/api/v1/notifications?unread=true", headers=headers).json()["unread_count"]
        == 22
    )
    assert client.post("/api/v1/notifications/read-all", headers=headers).status_code == 200
    assert client.get("/api/v1/notifications?unread=true", headers=headers).json()["items"] == []
    assert client.get("/api/v1/notifications?offset=-1", headers=headers).status_code == 422
    assert client.get("/api/v1/notifications").status_code == 401
    assert (
        client.put(
            "/api/v1/notifications/preferences",
            headers=headers,
            json={"email_enabled": True, "daily_enabled": False},
        ).status_code
        == 200
    )
    assert not client.get("/api/v1/notifications/preferences", headers=other).json()[
        "email_enabled"
    ]


@pytest.mark.parametrize("state", ["REDEEMED", "CANCELLED", "EXPIRED", "ELAPSED"])
def test_late_expiry_reminders_are_suppressed(client, state):
    _, headers, _, _, _, claimed, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        c = db.get(CouponClaim, UUID(claimed["id"]))
        if state == "ELAPSED":
            c.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            c.claimed_at = c.expires_at - timedelta(hours=1)
        else:
            c.status = state
        db.commit()
        expiry_reminder(db, {"claim_id": claimed["id"]})
        db.commit()
    assert client.get("/api/v1/notifications", headers=headers).json()["items"] == []


def test_email_capture_opt_in_and_duplicate_delivery(client):
    user = create_user(client)
    headers = bearer(login(client, user))
    assert (
        client.get("/api/v1/notifications/preferences", headers=headers).json()["email_mode"]
        == "LOCAL_CAPTURE"
    )
    with Session(client.app.state.engine) as db:
        notify(
            db,
            user_id=user.id,
            key="no-email",
            kind="TEST",
            title="Update",
            body="No tokens",
            link="/app",
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        db.add(NotificationPreference(user_id=user.id, email_enabled=True, daily_enabled=True))
        db.commit()
        notify(
            db,
            user_id=user.id,
            key="email",
            kind="TEST",
            title="Update",
            body="No tokens",
            link="/app",
        )
        db.commit()
        note = db.scalar(select(Notification).where(Notification.event_key == "email"))
        note_id = note.id
    drain(client)
    with Session(client.app.state.engine) as db:
        email_delivery(db, {"notification_id": str(note_id)})
        db.commit()
        assert db.scalar(select(func.count()).select_from(CapturedEmail)) == 1


def test_email_failure_rolls_back_delivery_retries_and_has_private_error(client):
    user = create_user(client)
    with Session(client.app.state.engine) as db:
        db.add(NotificationPreference(user_id=user.id, email_enabled=True, daily_enabled=True))
        db.commit()
        notify(
            db,
            user_id=user.id,
            key="retry",
            kind="TEST",
            title="Update",
            body="Private text",
            link="/app",
        )
        db.commit()

    class Broken:
        def send(self, db, note, recipient, *, idempotency_key):
            db.add(
                CapturedEmail(
                    notification_id=note.id, recipient=recipient, subject=note.title, body=note.body
                )
            )
            db.flush()
            raise RuntimeError("must-not-be-stored")

    broken = {"notification.email": lambda db, p: email_delivery(db, p, Broken())}
    for n in range(3):
        assert process_one(client.app.state.engine, broken)
        with Session(client.app.state.engine) as db:
            job = db.scalar(select(Job).where(Job.kind == "notification.email"))
            assert job.last_error == "RuntimeError"
            assert job.attempts == n + 1
            assert db.scalar(select(func.count()).select_from(CapturedEmail)) == 0
            if n < 2:
                assert job.status == "pending" and job.available_at > datetime.now(UTC)
                job.available_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
    admin = bearer(login(client, create_user(client, Role.ADMIN)))
    superadmin = bearer(login(client, create_user(client, Role.SUPER_ADMIN)))
    assert client.get("/api/v1/notifications/operations/failed", headers=admin).status_code == 403
    failed = client.get("/api/v1/notifications/operations/failed", headers=superadmin).json()
    assert len(failed) == 1 and "payload" not in failed[0]
    assert (
        client.post(
            f"/api/v1/notifications/operations/{failed[0]['id']}/retry", headers=superadmin
        ).status_code
        == 200
    )
    drain(client)
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(CapturedEmail)) == 1


def test_email_disabled_before_delivery_is_not_captured(client):
    user = create_user(client)
    with Session(client.app.state.engine) as db:
        pref = NotificationPreference(user_id=user.id, email_enabled=True, daily_enabled=True)
        db.add(pref)
        db.commit()
        notify(
            db, user_id=user.id, key="off", kind="TEST", title="Update", body="No mail", link="/app"
        )
        db.commit()
        pref.email_enabled = False
        db.commit()
    drain(client)
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(CapturedEmail)) == 0


def test_daily_scheduler_and_handler_are_idempotent_and_never_claim(client):
    _, _, store, _, user, headers, _ = fixture(client)
    assert search(client, headers, store).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: schedule_daily(client.app.state.engine), range(2)))
    drain(client)
    notes = client.get("/api/v1/notifications", headers=headers).json()["items"]
    assert len(notes) == 1 and notes[0]["kind"] == "DAILY_COUPON"
    assert schedule_daily(client.app.state.engine) == 0
    with Session(client.app.state.engine) as db:
        daily_notification(
            db,
            {
                "user_id": str(user.id),
                "business_date": str(datetime.now(ZoneInfo("Asia/Kolkata")).date()),
            },
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(CouponClaim)) == 0
    assert len(client.get("/api/v1/notifications", headers=headers).json()["items"]) == 1


def test_daily_opt_out_and_old_search_are_skipped(client):
    from app.daily.models import Recommendation

    _, _, store, _, user, headers, _ = fixture(client)
    search(client, headers, store)
    with Session(client.app.state.engine) as db:
        db.add(NotificationPreference(user_id=user.id, email_enabled=False, daily_enabled=False))
        db.commit()
    assert schedule_daily(client.app.state.engine) == 0
    with Session(client.app.state.engine) as db:
        db.get(NotificationPreference, user.id).daily_enabled = True
        db.execute(
            update(Recommendation).values(selected_at=datetime.now(UTC) - timedelta(days=31))
        )
        db.commit()
    assert schedule_daily(client.app.state.engine) == 0


def test_valid_reminder_becomes_stale_and_email_is_skipped_after_redemption(client):
    _, headers, _, _, _, claimed, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        claim = db.get(CouponClaim, UUID(claimed["id"]))
        db.add(
            NotificationPreference(user_id=claim.user_id, email_enabled=True, daily_enabled=True)
        )
        db.commit()
        expiry_reminder(db, {"claim_id": claimed["id"]})
        expiry_reminder(db, {"claim_id": claimed["id"]})
        db.commit()
        note = db.scalar(select(Notification).where(Notification.kind == "COUPON_EXPIRY_REMINDER"))
        assert note and note.valid_until == claim.expires_at
        claim.status = "REDEEMED"
        claim.redeemed_at = datetime.now(UTC)
        db.commit()
        email_delivery(db, {"notification_id": str(note.id)})
        db.commit()
        assert db.scalar(select(func.count()).select_from(CapturedEmail)) == 0
    response = client.get("/api/v1/notifications", headers=headers).json()
    assert len(response["items"]) == 1 and response["items"][0]["stale"]


def test_notification_handler_failure_cannot_roll_back_a_successful_claim(client):
    _, headers, _, _, _, claimed, _ = setup_coupon(client)
    with Session(client.app.state.engine) as db:
        db.execute(
            update(Job)
            .where(Job.kind != "coupon.claimed")
            .values(available_at=datetime.now(UTC) + timedelta(days=1))
        )
        db.commit()

    def fail_after_write(db, payload):
        claim_event(db, payload)
        raise RuntimeError("temporary delivery error")

    assert process_one(client.app.state.engine, {"coupon.claimed": fail_after_write})
    with Session(client.app.state.engine) as db:
        assert db.get(CouponClaim, UUID(claimed["id"])).status == "CLAIMED"
        assert db.scalar(select(func.count()).select_from(Notification)) == 0
        job = db.scalar(select(Job).where(Job.kind == "coupon.claimed"))
        assert job.status == "pending"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert process_one(client.app.state.engine, {"coupon.claimed": claim_event})
    assert (
        client.get("/api/v1/notifications", headers=headers).json()["items"][0]["kind"]
        == "COUPON_CLAIMED"
    )


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT"])
def test_merchant_offer_review_notifications_are_async(client, decision):
    from test_offers import action, fixture_offer, review

    owner, admin, _, _, _, offer = fixture_offer(client, approved=False)
    submitted = action(client, owner, offer, "SUBMIT").json()
    assert review(client, admin, submitted, decision, "Review feedback").status_code == 200
    assert client.get("/api/v1/notifications", headers=owner).json()["items"] == []
    drain(client)
    notes = client.get("/api/v1/notifications", headers=owner).json()["items"]
    assert {n["kind"] for n in notes} == {"MERCHANT_APPROVED", "OFFER_REVIEWED"}
    review_note = next(n for n in notes if n["kind"] == "OFFER_REVIEWED")
    assert ("approved" if decision == "APPROVE" else "rejected") in review_note["title"]


def test_daily_notification_suppressed_when_allowance_exhausted(client):
    from test_coupons import claim

    _, _, store, item, user, headers, _ = fixture(client)
    search(client, headers, store)
    assert claim(client, headers, item).status_code == 200
    with Session(client.app.state.engine) as db:
        daily_notification(
            db,
            {
                "user_id": str(user.id),
                "business_date": str(datetime.now(ZoneInfo("Asia/Kolkata")).date()),
            },
        )
        db.commit()
        assert (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.kind == "DAILY_COUPON")
            )
            == 0
        )
