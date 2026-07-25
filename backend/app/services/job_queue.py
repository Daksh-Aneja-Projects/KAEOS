"""KAEOS — durable job queue processor.

A DB-backed at-least-once queue that fits KAEOS's existing operational model
(leader-elected APScheduler jobs + owner-session sweeps) rather than adding a
Celery/Redis broker. The public surface is small:

  * ``enqueue(db, tenant_id, job_type, payload)`` — persist a job.
  * ``register_handler(job_type, coro)`` — map a type to an async handler.
  * ``process_jobs()`` — drain due jobs (leader only, called by the scheduler).
  * ``requeue_stuck_jobs()`` — recover jobs a dead worker left RUNNING.

Only the elected leader processes the queue, so claiming is effectively
single-threaded; the claim is still done as a conditional UPDATE (``WHERE
status='QUEUED'``) so a lost-lease overlap can never run a job twice.
"""
from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import MaintenanceSessionLocal
from app.models.jobs import Job

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}

_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_RETRY_BACKOFF_SECONDS = 30      # * attempts, so 30s, 60s, 90s...
_DEFAULT_MAX_JOBS_PER_TICK = 25


def register_handler(job_type: str, handler: Handler) -> None:
    """Register (or replace) the async handler for a job type."""
    _HANDLERS[job_type] = handler


def _is_leader() -> bool:
    try:
        from app.services.leader_lock import leader_lock
        return leader_lock.is_leader
    except Exception:
        return True  # no leader machinery -> single instance -> proceed


async def enqueue(db: AsyncSession, tenant_id: str, job_type: str, payload: dict,
                  *, max_attempts: int = 1, delay_seconds: int = 0) -> str:
    """Persist a job for durable, at-least-once execution. Returns the job id."""
    now = datetime.now(timezone.utc)
    job = Job(
        tenant_id=tenant_id,
        job_type=job_type,
        payload=payload or {},
        status="QUEUED",
        attempts=0,
        max_attempts=max(1, max_attempts),
        run_after=now + timedelta(seconds=max(0, delay_seconds)),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job.id


async def _claim_one(db: AsyncSession, now: datetime) -> Optional[Job]:
    """Atomically claim the oldest due QUEUED job, or return None."""
    cand = (await db.execute(
        select(Job)
        .where(Job.status == "QUEUED", Job.run_after <= now)
        .order_by(Job.created_at)
        .limit(1)
    )).scalar_one_or_none()
    if cand is None:
        return None
    # Conditional claim: only succeeds if the row is still QUEUED.
    res = await db.execute(
        update(Job)
        .where(Job.id == cand.id, Job.status == "QUEUED")
        .values(status="RUNNING", attempts=Job.attempts + 1,
                locked_by=_WORKER_ID, locked_at=now, updated_at=now)
    )
    await db.commit()
    if res.rowcount != 1:
        return None  # someone else claimed it in the overlap window
    await db.refresh(cand)
    return cand


async def process_jobs(max_jobs: int = _DEFAULT_MAX_JOBS_PER_TICK) -> dict:
    """Drain up to ``max_jobs`` due jobs. Leader-guarded; safe to call on a tick."""
    if not _is_leader():
        return {"leader": False, "succeeded": 0, "failed": 0, "retried": 0}

    counts = {"leader": True, "succeeded": 0, "failed": 0, "retried": 0}
    async with MaintenanceSessionLocal() as db:
        for _ in range(max_jobs):
            job = await _claim_one(db, datetime.now(timezone.utc))
            if job is None:
                break

            # Capture immutable identity up front: after a rollback the ORM object
            # is expired, so touching job.id would trigger a sync lazy-load in the
            # async context (MissingGreenlet). Reload by this id instead.
            jid = job.id
            job_type = job.job_type
            payload = dict(job.payload or {})

            handler = _HANDLERS.get(job_type)
            if handler is None:
                job.status = "FAILED"
                job.last_error = f"no handler registered for job_type '{job_type}'"
                await db.commit()
                counts["failed"] += 1
                logger.error("[JobQueue] no handler registered for job_type '%s'", job_type)
                continue

            try:
                await handler(payload)
            except Exception as exc:  # handler failed — retry with backoff or fail
                await db.rollback()
                # Re-load: the handler's own sessions are separate, but be safe.
                job = (await db.execute(select(Job).where(Job.id == jid))).scalar_one()
                if job.attempts < job.max_attempts:
                    job.status = "QUEUED"
                    job.run_after = datetime.now(timezone.utc) + timedelta(
                        seconds=_RETRY_BACKOFF_SECONDS * job.attempts)
                    counts["retried"] += 1
                    logger.warning("[JobQueue] job %s (%s) failed, retry %d/%d: %s",
                                   job.id, job.job_type, job.attempts, job.max_attempts, exc)
                else:
                    job.status = "FAILED"
                    counts["failed"] += 1
                    logger.error("[JobQueue] job %s (%s) permanently failed after %d attempt(s): %s",
                                 job.id, job.job_type, job.attempts, exc)
                job.last_error = str(exc)[:1024]
                job.locked_by = None
                await db.commit()
            else:
                job.status = "SUCCEEDED"
                job.last_error = None
                job.locked_by = None
                await db.commit()
                counts["succeeded"] += 1
    return counts


async def requeue_stuck_jobs(stuck_after_minutes: int = 30) -> list:
    """Recover jobs a crashed worker left RUNNING (at-least-once backstop).

    A job RUNNING longer than the threshold is requeued if it has attempts left,
    else marked FAILED so it surfaces instead of hanging forever. Returns the
    affected job ids. Leader-guarded.
    """
    if not _is_leader():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_after_minutes)
    touched: list[str] = []
    async with MaintenanceSessionLocal() as db:
        rows = (await db.execute(
            select(Job).where(Job.status == "RUNNING", Job.locked_at < cutoff)
        )).scalars().all()
        now = datetime.now(timezone.utc)
        for job in rows:
            if job.attempts < job.max_attempts:
                job.status = "QUEUED"
                job.run_after = now
                job.last_error = "requeued: worker died mid-run (at-least-once)"
            else:
                job.status = "FAILED"
                job.last_error = "orphaned: worker crashed and attempts exhausted"
            job.locked_by = None
            touched.append(job.id)
        if touched:
            await db.commit()
            logger.warning("[JobQueue] recovered %d stuck job(s): %s", len(touched), touched)
    return touched
