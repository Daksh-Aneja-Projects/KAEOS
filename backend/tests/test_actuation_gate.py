"""The /actuation consequence gate (P0.5 review finding).

The execute endpoint was the one execution path with NO gate at all: one API
call could delete data or move money on `require_role("operator")` alone.
High-consequence writes must pause in the HITL queue, and an approved write
must actually LAND through the shared resume path - fail-closed, never a
stamped success for a write that did not happen.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.actuation import ActionRecord
from app.models.domain import SkillExecution
from app.services.hitl_manager import HITLManager


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    from app.core.database import init_db
    asyncio.run(init_db())


@pytest.fixture(autouse=True)
def _mute_side_channels(monkeypatch):
    """Feed/notifier/audit are not under test; the notifier additionally opens
    a concurrent session on the :memory: StaticPool's single connection."""
    from app.services import notifier
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)
    monkeypatch.setattr(notifier, "notify_fire_and_forget", lambda *a, **k: None)
    # Force the in-memory HITL store even when a local Redis is running.
    async def _no_redis(self):
        return None
    monkeypatch.setattr(HITLManager, "_get_redis", _no_redis)
    # The resume runs the FULL gate pipeline now; enterprise-memory recall
    # embeds via the real local model - stub it so unit tests never touch the
    # GPU and never wait on a model load.
    from app.services.memory.enterprise_memory import EnterpriseMemoryService

    async def _no_recall(*a, **k):
        return []

    async def _no_store(*a, **k):
        return None

    monkeypatch.setattr(EnterpriseMemoryService, "recall_similar_situations", _no_recall)
    monkeypatch.setattr(EnterpriseMemoryService, "store_decision_memory", _no_store)


def _tenant(t):
    return {"tenant_id": t, "role": "operator", "name": "maker", "email": "maker@acme"}


def _body(**over):
    from app.api.routes.actuation import ActionIn
    base = dict(system="sandbox", object_type="record",
                external_id=f"obj-{uuid.uuid4().hex[:6]}",
                operation="UPDATE", payload={"note": "hello"})
    base.update(over)
    return ActionIn(**base)


def test_routine_actuation_applies_directly():
    from app.api.routes.actuation import execute_action

    t = f"tenant_act_{uuid.uuid4().hex[:6]}"

    async def run():
        async with AsyncSessionLocal() as db:
            out = await execute_action(_body(operation="CREATE"), tenant=_tenant(t), db=db)
        assert out["status"] == "APPLIED"

    asyncio.run(run())


def test_high_consequence_actuation_pauses_for_hitl():
    """DELETE (and anything matching HIGH_CONSEQUENCE_TAGS) never lands off a
    single API call: it becomes a PENDING_HITL row, with no ActionRecord."""
    from app.api.routes.actuation import execute_action

    t = f"tenant_act_{uuid.uuid4().hex[:6]}"
    ext_id = f"obj-{uuid.uuid4().hex[:6]}"

    async def run():
        async with AsyncSessionLocal() as db:
            await execute_action(_body(operation="CREATE", external_id=ext_id),
                                 tenant=_tenant(t), db=db)
            out = await execute_action(_body(operation="DELETE", external_id=ext_id),
                                       tenant=_tenant(t), db=db)
        assert out["status"] == "PENDING_HITL"
        exec_id = out["execution_id"]

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.status == "PENDING_HITL"
            assert row.context["actuation"]["operation"] == "DELETE"
            deletes = (await s.execute(select(ActionRecord).where(
                ActionRecord.tenant_id == t,
                ActionRecord.operation == "DELETE"))).scalars().all()
            assert deletes == [], "the write must not land before approval"

    asyncio.run(run())


def test_approval_applies_the_paused_write():
    """Approving the paused actuation applies it through the shared resume
    path: a real ActionRecord attributed to the approver, and the execution
    row finalized by the run (not stamped by the approve route)."""
    from app.api.routes.actuation import execute_action
    from app.services.hitl_manager import hitl_manager

    t = f"tenant_act_{uuid.uuid4().hex[:6]}"
    ext_id = f"obj-{uuid.uuid4().hex[:6]}"

    async def run():
        async with AsyncSessionLocal() as db:
            await execute_action(_body(operation="CREATE", external_id=ext_id),
                                 tenant=_tenant(t), db=db)
            out = await execute_action(_body(operation="DELETE", external_id=ext_id),
                                       tenant=_tenant(t), db=db)
        exec_id = out["execution_id"]

        ok = await hitl_manager.resolve_hitl(
            exec_id, approved=True, approver="checker@acme", tenant_id=t)
        assert ok is True
        # Drain the background resume task by AWAITING it, not by polling the
        # row. Two prior shapes both flaked: a fixed sleep(0.3) raced the ~3s
        # resume, and a DB poll starved it of the StaticPool's single shared
        # connection - and when the poll's cap expired on a slow CI runner, the
        # assertion failure made asyncio.run() cancel the resume MID-DB-OP,
        # which poisoned the pooled connection and cascaded "no such table"
        # into every later teardown sweep on that xdist worker. Waiting on the
        # task set is deterministic (no contention, no cap tuned to hardware),
        # and if the resume ever genuinely hangs, the bounded wait still fails
        # the test - after which the task has been awaited, not abandoned.
        others = [task for task in asyncio.all_tasks()
                  if task is not asyncio.current_task()]
        if others:
            _done, pending = await asyncio.wait(others, timeout=120)
            for task in pending:
                task.cancel()
            if pending:
                # Let the cancellation unwind through SQLAlchemy's finally
                # blocks so the shared connection is released sanely.
                await asyncio.gather(*pending, return_exceptions=True)
            assert not pending, "the HITL resume task did not finish within 120s"
        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
        assert row.status == "SUCCESS_CLEAN"
        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.hitl_approver == "checker@acme"
            rec = (await s.execute(select(ActionRecord).where(
                ActionRecord.tenant_id == t,
                ActionRecord.operation == "DELETE"))).scalar_one()
            assert rec.status == "APPLIED"
            assert rec.actor == "checker@acme"
            assert rec.execution_id == exec_id

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
