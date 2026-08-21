"""H11: a mission-step approval retires the paired HITL record instead of
leaving it orphaned and still-approvable in the /hitl and /skills/hitl queues.

The two HITL stores never reconciled: resolving a mission step touched only the
MissionStep, and the paused run's hitl_manager record (keyed by that run's
execution id) lingered. discard_pending retires it in lockstep, tenant-scoped,
with no resume. (Both resume paths already pass hitl_pre_approved=True, so the
'mission approval confers more power' sub-claim of the finding was overstated.)"""
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.domain import SkillExecution
from app.models.execution_status import ExecutionStatus
from app.services.hitl_manager import hitl_manager

TENANT = "tenant_h11"


async def _pending_ids(tenant):
    return {r["exec_id"] for r in await hitl_manager.list_pending(tenant)}


@pytest.mark.asyncio
async def test_discard_pending_retires_record_tenant_scoped(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(hitl_manager, "_get_redis", _no_redis)
    hitl_manager._memory = {}

    exec_id = "mission-abc12345-s1-deadbe"
    await hitl_manager.request_human_confirmation(
        {"skill_id": "s", "steps": []},
        {"execution_id": exec_id, "tenant_id": TENANT,
         "mission_id": "abc", "mission_step_seq": 1})

    assert exec_id in await _pending_ids(TENANT), "pause is listed as pending"

    # Another tenant cannot retire it.
    assert await hitl_manager.discard_pending(exec_id, "other-tenant") is False
    assert exec_id in await _pending_ids(TENANT)

    # The owner retires it: it leaves the pending list, with no resume.
    assert await hitl_manager.discard_pending(exec_id, TENANT) is True
    assert exec_id not in await _pending_ids(TENANT)

    # The DB-backed queue row is finalized too, so /skills/hitl no longer lists it.
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(SkillExecution).where(SkillExecution.id == exec_id))).scalar_one_or_none()
    assert row is not None and row.status == ExecutionStatus.HUMAN_OVERRIDDEN
