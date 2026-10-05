"""A scheduler can drain a small batch without a persistent serverless worker."""

import hmac
from time import monotonic

from fastapi import APIRouter, Request

from app.auth.service import AuthError
from app.jobs.service import process_one
from app.jobs.worker import handlers
from app.notifications.events import schedule_daily

router = APIRouter(prefix="/api/internal", include_in_schema=False)


@router.get("/jobs")
@router.post("/jobs")
def run_jobs(request: Request) -> dict[str, int]:
    secret = request.app.state.settings.cron_secret.get_secret_value()
    if not secret:
        raise AuthError("NOT_FOUND", "Not found.", 404)
    actual = request.headers.get("authorization", "").encode()
    if not hmac.compare_digest(actual, f"Bearer {secret}".encode()):
        raise AuthError("FORBIDDEN", "Scheduler authentication required.", 403)
    engine = request.app.state.engine
    deadline = monotonic() + 20
    scheduled = schedule_daily(engine)
    processed = 0
    registry = handlers()
    while processed < 20 and monotonic() < deadline:
        if not process_one(engine, registry):
            break
        processed += 1
    return {"scheduled": scheduled, "processed": processed}
