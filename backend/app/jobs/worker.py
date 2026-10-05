import logging
import signal
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import make_engine
from app.coupons.service import claim_event, expire_claim
from app.jobs.service import Handler, process_one
from app.notifications.events import (
    daily_notification,
    expiry_reminder,
    merchant_approved,
    offer_reviewed,
    schedule_daily,
)
from app.notifications.service import email_delivery
from app.offers.service import expire_offer
from app.redemptions.service import redeemed_event

HEARTBEAT = Path.home() / ".nearperk" / "worker-heartbeat"


def noop(session: Session, payload: dict[str, Any]) -> None:
    """Foundation smoke job; no business effects."""


def handlers() -> dict[str, Handler]:
    return {
        "system.noop": noop,
        "offer.expire": expire_offer,
        "coupon.claimed": claim_event,
        "coupon.expire": expire_claim,
        "coupon.redeemed": redeemed_event,
        "notification.expiry": expiry_reminder,
        "notification.merchant_approved": merchant_approved,
        "notification.daily": daily_notification,
        "notification.email": email_delivery,
        "notification.offer_reviewed": offer_reviewed,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='{"service":"worker","message":"%(message)s"}')
    HEARTBEAT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = Settings()
    engine = make_engine(settings.database_url)
    stop = threading.Event()

    def shutdown(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    next_daily_poll = 0.0
    try:
        while not stop.is_set():
            try:
                if time.monotonic() >= next_daily_poll:
                    try:
                        schedule_daily(engine)
                    except Exception as exc:
                        logging.error("daily_schedule_failed:%s", type(exc).__name__)
                    next_daily_poll = time.monotonic() + 60
                worked = process_one(
                    engine,
                    handlers(),
                )
                HEARTBEAT.write_text(str(time.time()))
                if not worked:
                    stop.wait(settings.worker_poll_seconds)
            except Exception as exc:
                logging.error("poll_failed:%s", type(exc).__name__)
                stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()
        HEARTBEAT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
