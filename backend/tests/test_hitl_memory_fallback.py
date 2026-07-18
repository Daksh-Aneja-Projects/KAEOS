"""
Regression: HITL must work without Redis.

The old hitl_manager logged "falling back to in-memory storage" but stored
nothing - every Gate-3 pause was announced in the activity feed yet could not
be listed, approved, or rejected. Gated (synthetic) skills additionally had no
SkillExecution row at pause time, so even the DB path could not resolve them.

These tests run the full loop in one process (as a single-instance deployment
does): request -> list_pending -> resolve(approve) -> resume executes the
stored skill contract and persists a real SkillExecution row.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.domain import SkillExecution
from app.services.hitl_manager import HITLManager


class _NoRedisHITLManager(HITLManager):
    async def _get_redis(self):
        return None


def _skill(skill_id="hitl_fallback_test_skill"):
    return {
        "skill_id": skill_id,
        "department": "support",
        "steps": [{"step": 1, "name": "Assess", "prompt": "Assess the test case."}],
        "compliance_tags": [],
        "confidence": 0.5,
    }


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    """The test DB may be empty - create the ORM schema once."""
    from app.core.database import init_db
    asyncio.run(init_db())


@pytest.fixture(autouse=True)
def _mute_activity_feed(monkeypatch):
    """The feed write is not under test and the test DB may lack its table."""
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)


def test_pending_is_stored_listed_and_rejectable():
    mgr = _NoRedisHITLManager()
    exec_id = f"exec-test-{uuid.uuid4().hex[:8]}"
    ctx = {"execution_id": exec_id, "tenant_id": "tenant_test_hitl", "_skill_obj": object()}

    async def run():
        out = await mgr.request_human_confirmation(_skill(), ctx)
        assert out["pending"] is True and out["execution_id"] == exec_id

        pending = await mgr.list_pending("tenant_test_hitl")
        assert any(p["exec_id"] == exec_id for p in pending), "pause not listed"
        # private context keys must not be stored
        rec = next(p for p in pending if p["exec_id"] == exec_id)
        assert "_skill_obj" not in rec["context"]

        ok = await mgr.resolve_hitl(exec_id, approved=False, approver="tester", reason="no")
        assert ok is True
        status = await mgr.get_hitl_status(exec_id)
        assert status["status"] == "RESOLVED" and status["decision"] is False

        pending_after = await mgr.list_pending("tenant_test_hitl")
        assert not any(p["exec_id"] == exec_id for p in pending_after)

    asyncio.run(run())


def test_gate_pause_persists_db_row_and_approve_resumes(monkeypatch):
    """A Gate-3 pause must create a PENDING_HITL SkillExecution row (single
    queue, restart-safe) and approving must execute the stored contract."""
    mgr = _NoRedisHITLManager()
    exec_id = f"exec-test-{uuid.uuid4().hex[:8]}"
    ctx = {"execution_id": exec_id, "tenant_id": "tenant_test_hitl",
           "instruction": "resume test intent"}

    ran = {}

    class _FakeEngine:
        async def run(self, skill_def, context, execution_id, tenant_id, skill_obj=None):
            ran["skill_id"] = skill_def["skill_id"]
            ran["steps"] = skill_def["steps"]
            ran["hitl_approved"] = context.get("hitl_approved")
            return {"status": "SUCCESS_CLEAN", "reasoning_chain": [{}]}

    import app.services.skill_executor as se
    monkeypatch.setattr(se, "SkillExecutionEngine", _FakeEngine)

    async def run():
        await mgr.request_human_confirmation(_skill("hitl_resume_test"), ctx)
        # unification: the pause IS a DB row - visible in the single queue
        async with AsyncSessionLocal() as s:
            row = (await s.execute(
                select(SkillExecution).where(SkillExecution.id == exec_id)
            )).scalar_one_or_none()
            assert row is not None, "gate pause must persist a queue row"
            assert row.status == "PENDING_HITL"
            assert row.hitl_required is True
            assert row.route_type == "GATED_AGENT"

        ok = await mgr.resolve_hitl(exec_id, approved=True, approver="tester")
        assert ok is True
        # resolve schedules the resume as a task - drain it
        await asyncio.sleep(0.2)

        assert ran.get("skill_id") == "hitl_resume_test", "resume never executed the stored contract"
        assert ran.get("hitl_approved") is True
        assert ran.get("steps"), "stored steps were lost"

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
