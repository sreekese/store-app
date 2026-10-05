from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.jobs.models import Job

Handler = Callable[[Session, dict[str, Any]], None]


def enqueue(
    session: Session,
    *,
    kind: str,
    payload: dict[str, Any],
    key: str,
    available_at: datetime | None = None,
) -> UUID:
    """Caller owns the transaction: enqueue alongside the business write."""
    # A read of an existing job avoids waiting on a worker's row lock during deduplication.
    existing = session.scalar(select(Job.id).where(Job.deduplication_key == key))
    if existing is not None:
        return existing
    job_id = session.scalar(
        insert(Job)
        .values(
            id=uuid4(),
            kind=kind,
            payload=payload,
            deduplication_key=key,
            available_at=available_at or datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=[Job.deduplication_key])
        .returning(Job.id)
    )
    if job_id is not None:
        return job_id
    existing = session.scalar(select(Job.id).where(Job.deduplication_key == key))
    if not (existing is not None):
        raise RuntimeError("Required application state is unavailable")
    return existing


def process_one(engine: Engine, handlers: dict[str, Handler]) -> bool:
    """Lock through processing. Crashes roll back; competing workers skip the lock.

    Handlers must keep database effects in this session. External effects require
    their own idempotency keys; this is at-least-once processing, not exactly-once delivery.
    """
    with Session(engine) as session, session.begin():
        job = session.scalar(
            select(Job)
            .where(Job.status == "pending", Job.available_at <= func.now())
            .order_by(Job.available_at, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.attempts += 1
        try:
            with session.begin_nested():
                handlers[job.kind](session, job.payload)
        except Exception as exc:
            # Store only exception type, never payloads, tokens, or personal data.
            job.last_error = type(exc).__name__
            if job.attempts >= job.max_attempts:
                job.status = "failed"
            else:
                job.available_at = datetime.now(UTC) + timedelta(seconds=min(2**job.attempts, 300))
        else:
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.last_error = None
    return True
