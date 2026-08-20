"""S5.6 — the leader's tick drains jobs concurrently, not one at a time.

``process_jobs`` used to claim and await handlers strictly sequentially on one
session, so a single slow handler (they can call LLMs) starved everything queued
behind it. Execution is now bounded-concurrent inside the leader's tick.

Same setup as ``test_job_queue.py``: the processor runs on the owner
(maintenance) session, which in tests is the app engine, so the ``jobs`` table is
created there and leadership is forced on.
"""
from datetime import datetime, timezone

import asyncio
import pytest

from app.services import job_queue
from app.core.database import engine as app_engine, MaintenanceSessionLocal
from app.models.jobs import Job


T = "tenant_jobs_conc"
SLOW = 0.3


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


async def _enqueue(job_type, payload=None, **kw):
    async with MaintenanceSessionLocal() as db:
        return await job_queue.enqueue(db, T, job_type, payload or {}, **kw)


async def _get(job_id) -> Job:
    from sqlalchemy import select
    async with MaintenanceSessionLocal() as db:
        return (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()


def _is_future(dt) -> bool:
    """SQLite drops tzinfo on DateTime(timezone=True); Postgres keeps it."""
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware > datetime.now(timezone.utc)


async def test_slow_handlers_run_concurrently_not_head_of_line():
    """Three 0.3s jobs finish in ~0.3s, not ~0.9s: no head-of-line blocking."""
    async def slow(payload):
        await asyncio.sleep(SLOW)
    job_queue.register_handler("s5_slow", slow)

    ids = [await _enqueue("s5_slow") for _ in range(3)]

    started = asyncio.get_running_loop().time()
    counts = await job_queue.process_jobs(concurrency=3)
    elapsed = asyncio.get_running_loop().time() - started

    assert counts == {"leader": True, "succeeded": 3, "failed": 0, "retried": 0}
    for job_id in ids:
        job = await _get(job_id)
        assert job.status == "SUCCEEDED"
        assert job.attempts == 1
        assert job.locked_by is None
    # Sequential would be 3 * 0.3 = 0.9s. Generous bound for a loaded CI box.
    assert elapsed < 0.6, f"jobs still drained sequentially ({elapsed:.2f}s)"


async def test_concurrency_is_bounded_by_the_semaphore():
    """Handlers really do overlap, and never more than ``concurrency`` at once."""
    inflight = 0
    peak = 0

    async def tracked(payload):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        try:
            await asyncio.sleep(0.05)
        finally:
            inflight -= 1
    job_queue.register_handler("s5_tracked", tracked)

    for _ in range(4):
        await _enqueue("s5_tracked")

    counts = await job_queue.process_jobs(concurrency=2)

    assert counts["succeeded"] == 4
    assert peak == 2, f"expected exactly 2 handlers in flight, saw {peak}"


async def test_one_failing_job_retries_while_its_peers_succeed():
    """A raiser lands its retry/backoff state without disturbing concurrent jobs."""
    async def ok(payload):
        await asyncio.sleep(0.05)

    async def boom(payload):
        await asyncio.sleep(0.05)
        raise RuntimeError("concurrent-kaboom")

    job_queue.register_handler("s5_ok", ok)
    job_queue.register_handler("s5_boom", boom)

    bad_id = await _enqueue("s5_boom", max_attempts=3)
    good_ids = [await _enqueue("s5_ok") for _ in range(2)]

    counts = await job_queue.process_jobs(concurrency=3)

    assert counts == {"leader": True, "succeeded": 2, "failed": 0, "retried": 1}
    for job_id in good_ids:
        assert (await _get(job_id)).status == "SUCCEEDED"

    bad = await _get(bad_id)
    assert bad.status == "QUEUED"           # attempts left, so back in the queue
    assert bad.attempts == 1
    assert bad.locked_by is None
    assert "concurrent-kaboom" in (bad.last_error or "")
    assert _is_future(bad.run_after), "retry must be delayed by the backoff"

    # Backoff holds: an immediate second tick must not re-claim it.
    assert (await job_queue.process_jobs(concurrency=3))["retried"] == 0
    assert (await _get(bad_id)).attempts == 1
