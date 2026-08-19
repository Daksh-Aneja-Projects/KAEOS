"""KAEOS — durable background job queue.

Replaces fire-and-forget ``asyncio.create_task`` for long-running work (the
deployment pipeline first). A job is PERSISTED before its work starts, so a
worker crash between enqueue and completion is recoverable: the row is still in
the table and the leader-guarded processor (or the stuck-job reaper) picks it up.

At-least-once delivery: a job claimed but left RUNNING by a dead worker is
requeued (up to ``max_attempts``) by the reaper, so handlers should be
idempotent. Tenant-scoped; RLS on Postgres. The processor runs on the owner
session (leader only) so it can drain every tenant's jobs.
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid




class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    job_type = Column(String(64), nullable=False)          # dispatch key -> handler
    payload = Column(JSON, nullable=False, default=dict)

    # QUEUED -> RUNNING -> SUCCEEDED | FAILED (FAILED after attempts exhausted).
    status = Column(String(16), nullable=False, default="QUEUED", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)

    run_after = Column(DateTime(timezone=True), nullable=False)   # earliest eligible run
    locked_by = Column(String, nullable=True)                     # worker id holding it
    locked_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(1024), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # The claim query scans QUEUED rows eligible to run now, oldest first.
    __table_args__ = (
        Index("ix_jobs_claim", "status", "run_after"),
    )
