import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.database import make_engine
from app.core.readiness import database_ready
from app.jobs.models import Job
from app.jobs.service import enqueue, process_one

pytestmark = pytest.mark.integration


@pytest.fixture
def engine() -> Iterator[Engine]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
    db = make_engine(url)
    assert db.url.database and db.url.database.endswith("_test"), "Refuse non-test database"
    with db.begin() as connection:
        connection.execute(delete(Job))
    yield db
    db.dispose()


def add(engine: Engine, key: str | None = None) -> Any:
    with Session(engine) as session, session.begin():
        return enqueue(session, kind="test", payload={}, key=key or str(uuid4()))


def test_database_migrations_and_postgis(engine: Engine) -> None:
    assert database_ready(engine)


def test_enqueue_is_idempotent(engine: Engine) -> None:
    assert add(engine, "same-event") == add(engine, "same-event")


def test_enqueue_rolls_back_with_business_transaction(engine: Engine) -> None:
    with Session(engine) as session:
        enqueue(session, kind="test", payload={}, key="rolled-back")
        session.rollback()
    with Session(engine) as session:
        assert session.scalar(select(Job.id)) is None


def test_success_and_no_duplicate_processing(engine: Engine) -> None:
    job_id = add(engine)
    seen: list[str] = []
    assert process_one(engine, {"test": lambda s, p: seen.append("processed")})
    assert not process_one(engine, {"test": lambda s, p: seen.append("duplicate")})
    assert seen == ["processed"]
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job and job.status == "completed" and job.attempts == 1


def test_failures_retry_then_move_to_failed(engine: Engine) -> None:
    job_id = add(engine)

    def fail(session: Session, payload: dict[str, Any]) -> None:
        enqueue(session, kind="test", payload={}, key="must-rollback")
        raise ValueError("private information must not be stored")

    for attempt in range(1, 4):
        assert process_one(engine, {"test": fail})
        with Session(engine) as session, session.begin():
            job = session.get(Job, job_id)
            assert job and job.attempts == attempt
            assert job.last_error == "ValueError"
            assert job.status == ("failed" if attempt == 3 else "pending")
            assert (
                session.scalar(select(Job.id).where(Job.deduplication_key == "must-rollback"))
                is None
            )
            if attempt < 3:
                assert job.available_at > datetime.now(UTC)
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not process_one(engine, {"test": fail})


def test_competing_workers_do_not_process_same_job(engine: Engine) -> None:
    add(engine)
    started, release = Event(), Event()
    calls: list[str] = []

    def handler(session: Session, payload: dict[str, Any]) -> None:
        calls.append("once")
        started.set()
        assert release.wait(timeout=4)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(process_one, engine, {"test": handler})
        try:
            assert started.wait(timeout=3)
            assert not process_one(engine, {"test": handler})
        finally:
            release.set()
        assert first.result(timeout=5)
    assert calls == ["once"]


def test_crash_rolls_back_claim_for_next_worker(engine: Engine) -> None:
    job_id = add(engine)

    def crash(session: Session, payload: dict[str, Any]) -> None:
        raise SystemExit("simulate process termination")

    with pytest.raises(SystemExit):
        process_one(engine, {"test": crash})
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job and job.status == "pending" and job.attempts == 0
    assert process_one(engine, {"test": lambda s, p: None})
