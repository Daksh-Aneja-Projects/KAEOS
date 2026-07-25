"""Durable job queue — persistence, at-least-once execution, retry, and recovery.

The processor runs on the owner (maintenance) session, so these tests create and
drive the ``jobs`` table on that same engine and force leader=True.
"""
import pytest

from app.services import job_queue
from app.core.database import engine as app_engine, MaintenanceSessionLocal
from app.models.jobs import Job

pytestmark = pytest.mark.asyncio

T = "tenant_jobs"


@pytest.fixture(autouse=True)
async def _jobs_table(monkeypatch):
    # The processor is leader-guarded; force leadership on in tests.
    monkeypatch.setattr(job_queue, "_is_leader", lambda: True)
    async with app_engine.begin() as conn:
        await conn.run_sync(Job.__table__.create, checkfirst=True)
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM jobs"))
    yield
    async with app_engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM jobs"))


async def _enqueue(job_type, payload, **kw):
    async with MaintenanceSessionLocal() as db:
        return await job_queue.enqueue(db, T, job_type, payload, **kw)


async def _get(job_id) -> Job:
    from sqlalchemy import select
    async with MaintenanceSessionLocal() as db:
        return (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()


async def test_enqueue_then_process_runs_handler_and_succeeds():
    seen = {}
    async def handler(payload):
        seen.update(payload)
    job_queue.register_handler("t_ok", handler)

    job_id = await _enqueue("t_ok", {"hello": "world"})
    result = await job_queue.process_jobs()

    assert result["succeeded"] == 1
    assert seen == {"hello": "world"}
    job = await _get(job_id)
    assert job.status == "SUCCEEDED"
    assert job.attempts == 1
    assert job.locked_by is None


async def test_no_handler_marks_failed():
    job_id = await _enqueue("t_unregistered", {})
    result = await job_queue.process_jobs()
    assert result["failed"] == 1
    job = await _get(job_id)
    assert job.status == "FAILED"
    assert "no handler" in (job.last_error or "")


async def test_failure_without_retries_marks_failed():
    async def boom(payload):
        raise RuntimeError("kaboom")
    job_queue.register_handler("t_boom", boom)

    job_id = await _enqueue("t_boom", {}, max_attempts=1)
    result = await job_queue.process_jobs()
    assert result["failed"] == 1
    job = await _get(job_id)
    assert job.status == "FAILED"
    assert "kaboom" in (job.last_error or "")
    assert job.attempts == 1


async def test_failure_with_retries_requeues_with_backoff():
    async def boom(payload):
        raise RuntimeError("try-again")
    job_queue.register_handler("t_retry", boom)

    job_id = await _enqueue("t_retry", {}, max_attempts=3)
    result = await job_queue.process_jobs()

    assert result["retried"] == 1
    job = await _get(job_id)
    assert job.status == "QUEUED"          # back in the queue
    assert job.attempts == 1               # one attempt consumed
    assert "try-again" in (job.last_error or "")

    # Backoff pushed run_after into the future: an immediate second tick must NOT
    # re-claim it (attempts stays 1), proving the retry is delayed, not hot-looped.
    result2 = await job_queue.process_jobs()
    assert result2["retried"] == 0 and result2["failed"] == 0
    assert (await _get(job_id)).attempts == 1


async def test_process_is_noop_for_non_leader(monkeypatch):
    monkeypatch.setattr(job_queue, "_is_leader", lambda: False)
    async def handler(payload):
        raise AssertionError("must not run when not leader")
    job_queue.register_handler("t_leader", handler)
    await _enqueue("t_leader", {})
    result = await job_queue.process_jobs()
    assert result == {"leader": False, "succeeded": 0, "failed": 0, "retried": 0}


async def test_reaper_requeues_stuck_running_job():
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import update
    job_id = await _enqueue("t_stuck", {}, max_attempts=2)
    # Simulate a worker that claimed it then died: RUNNING, attempts=1, old lock.
    async with MaintenanceSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(
                status="RUNNING", attempts=1, locked_by="dead-worker",
                locked_at=datetime.now(timezone.utc) - timedelta(hours=2))
        )
        await db.commit()

    recovered = await job_queue.requeue_stuck_jobs(stuck_after_minutes=30)
    assert job_id in recovered
    job = await _get(job_id)
    assert job.status == "QUEUED"          # requeued (attempts left)
    assert job.locked_by is None


async def test_reaper_fails_stuck_job_when_attempts_exhausted():
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import update
    job_id = await _enqueue("t_stuck2", {}, max_attempts=1)
    async with MaintenanceSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(
                status="RUNNING", attempts=1, locked_by="dead-worker",
                locked_at=datetime.now(timezone.utc) - timedelta(hours=2))
        )
        await db.commit()

    recovered = await job_queue.requeue_stuck_jobs(stuck_after_minutes=30)
    assert job_id in recovered
    job = await _get(job_id)
    assert job.status == "FAILED"          # no attempts left -> surfaced as failed
