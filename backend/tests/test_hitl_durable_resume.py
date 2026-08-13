"""Durable HITL-resume (review theme C): a crash between a human approval and
the resumed run's completion must never lose the run.

Every approval enqueues a `hitl_resume` job ATOMICALLY with the approval CAS
(same session/commit); the job fires after a backstop delay and is idempotent
on execution_id, so the normal in-process resume makes it a no-op while a
crashed one is recovered by the leader's queue processor.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.domain import SkillExecution
from app.models.jobs import Job
from app.services.hitl_manager import HITLManager


class _NoRedisHITLManager(HITLManager):
    async def _get_redis(self):
        return None


def _skill(skill_id):
    return {"skill_id": skill_id, "department": "support",
            "steps": [{"id": "s1", "action": "log", "message": "ok"}],
            "compliance_tags": [], "confidence": 0.5}


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    from app.core.database import init_db
    asyncio.run(init_db())


@pytest.fixture(autouse=True)
def _mute_side_channels(monkeypatch):
    from app.services import notifier
    from app.services.activity_feed import ActivityFeedService
    from app.services.memory.enterprise_memory import EnterpriseMemoryService

    async def _noop(self, **kwargs):
        return None

    async def _no_recall(*a, **k):
        return []

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)
    monkeypatch.setattr(notifier, "notify_fire_and_forget", lambda *a, **k: None)
    monkeypatch.setattr(EnterpriseMemoryService, "recall_similar_situations", _no_recall)
    monkeypatch.setattr(EnterpriseMemoryService, "store_decision_memory", _no_recall)


def test_approval_enqueues_a_durable_resume_job():
    """The backstop job lands with the approval - no crash window between
    'human said yes' and 'the work is guaranteed to run'."""
    mgr = _NoRedisHITLManager()
    exec_id = f"exec-dur-{uuid.uuid4().hex[:8]}"
    t = f"tenant_dur_{uuid.uuid4().hex[:6]}"

    async def run():
        await mgr.request_human_confirmation(
            _skill("durable_test"), {"execution_id": exec_id, "tenant_id": t})
        ok = await mgr.resolve_hitl(exec_id, approved=True, approver="tester")
        assert ok is True
        async with AsyncSessionLocal() as s:
            job = (await s.execute(select(Job).where(
                Job.job_type == "hitl_resume", Job.tenant_id == t))).scalar_one()
            assert job.payload["execution_id"] == exec_id
            assert job.status == "QUEUED"
            assert job.max_attempts == 3
        await asyncio.sleep(0.4)  # let the immediate resume drain

    asyncio.run(run())


def test_backstop_handler_noops_when_already_completed():
    """Idempotency: the delayed job firing after a successful resume must not
    re-run the skill."""
    from app.services.job_handlers import _run_hitl_resume

    mgr = _NoRedisHITLManager()
    exec_id = f"exec-dur-{uuid.uuid4().hex[:8]}"
    t = f"tenant_dur_{uuid.uuid4().hex[:6]}"

    async def run():
        await mgr.request_human_confirmation(
            _skill("durable_noop"), {"execution_id": exec_id, "tenant_id": t})
        await mgr.resolve_hitl(exec_id, approved=True, approver="tester")
        await asyncio.sleep(0.4)  # immediate resume completes (log step)

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.status == "SUCCESS_CLEAN"
            first_completed_at = row.completed_at

        # The backstop fires later - must be a no-op, not a second run.
        await _run_hitl_resume({"execution_id": exec_id, "fallback_record": None})
        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.completed_at == first_completed_at

    asyncio.run(run())


def test_backstop_recovers_a_crashed_resume():
    """Crash simulation: approval landed (row RUNNING, job QUEUED) but the
    in-process resume died with the process. The handler re-runs it from the
    durable job payload and the execution completes."""
    from app.services.job_handlers import _run_hitl_resume

    mgr = _NoRedisHITLManager()
    exec_id = f"exec-dur-{uuid.uuid4().hex[:8]}"
    t = f"tenant_dur_{uuid.uuid4().hex[:6]}"

    async def run():
        await mgr.request_human_confirmation(
            _skill("durable_crash"), {"execution_id": exec_id, "tenant_id": t})

        # Approve but simulate the process dying before the in-process task
        # ran: capture the durable payload exactly as resolve_hitl stored it.
        record = await mgr._get_record(exec_id)
        import app.services.hitl_manager as hm

        async def _crashed(self, execution_id, fallback_record=None):
            return False  # the in-process attempt never happens

        # Patch method on the instance to simulate the crash window.
        mgr._resume_from_hitl = _crashed.__get__(mgr)
        await mgr.resolve_hitl(exec_id, approved=True, approver="tester")
        del mgr._resume_from_hitl  # restore the real resume
        await asyncio.sleep(0.1)

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.status == "PENDING_HITL"      # approved, never ran
            assert row.agent_state == "RUNNING"
            job = (await s.execute(select(Job).where(
                Job.job_type == "hitl_resume", Job.tenant_id == t))).scalar_one()
            payload = dict(job.payload)

        # The recovered process's queue fires the handler with the payload.
        # The singleton hitl_manager handles it (fresh process, real resume).
        await _run_hitl_resume(payload)
        await asyncio.sleep(0.1)

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.status == "SUCCESS_CLEAN"
            assert row.completed_at is not None

    asyncio.run(run())
