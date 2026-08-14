"""Fairness BLOCK -> real HITL queue, and HITL approval clears the finding.

Contract: a gated run that hits a fairness block yields PENDING_HITL (a real
approval row an approver can act on), NOT a terminal BLOCKED_FAIRNESS dead-end.
On approved resume the same finding is overridden and the action proceeds; a
request cannot smuggle the override.
"""
import uuid

import pytest

from app.agents.runtime import AgentExecutor
from app.core.database import AsyncSessionLocal, init_db
from app.models.domain import Skill, SkillExecution
from app.models.fairness import FairnessAuditLog
from app.services.hitl_manager import hitl_manager

# Cohort with a clear, statistically significant adverse impact on gender.
_ADVERSE = {"gender": {"female": {"selected": 10, "total": 100},
                       "male": {"selected": 60, "total": 100}}}


class _FakeCompliance:
    async def check_before_execution(self, tags, context):
        return []

    def enforce_audit_requirements(self, *a, **k):
        return True


class _FakeExecEngine:
    def __init__(self):
        self.ran = False

    async def run(self, skill, context, execution_id, tenant_id, skill_obj=None,
                  compliance_warnings=None):
        self.ran = True
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [],
                "execution_id": execution_id, "steps_completed": 1, "duration_ms": 1}


class _FakeFeed:
    async def emit(self, **kwargs):
        return None


class _FakeHITL:
    def __init__(self):
        self.called = False

    async def request_human_confirmation(self, skill, context):
        self.called = True
        return {"pending": True, "execution_id": context.get("execution_id")}


def _skill_obj(tenant, sid):
    return Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id=tenant,
                 department="hr", domain="hr", status="ACTIVE", confidence=0.85,
                 compliance_tags=[], steps=[{"action": "screen candidates"}],
                 execution_count=1, success_rate=1.0)


def _skill_dict(sid):
    return {"skill_id": sid, "department": "hr", "compliance_tags": [],
            "confidence": 0.85, "steps": [{"action": "screen candidates"}]}


async def test_fairness_block_routes_to_real_hitl_queue(monkeypatch):
    """Adverse cohort -> PENDING_HITL with a real pending approval + DB row."""
    from app.services.llm_router import LLMRouter

    async def boom(self, *a, **k):
        raise AssertionError("statistical path must not consult the LLM")

    monkeypatch.setattr(LLMRouter, "complete", boom)
    await init_db()

    tenant = f"tenant_fh_{uuid.uuid4().hex[:6]}"
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    sid = "hr_screen_block"

    ex = AgentExecutor(_FakeCompliance(), hitl_manager)  # REAL hitl manager
    ex._activity_feed = _FakeFeed()
    ex._exec_engine = _FakeExecEngine()

    ctx = {"tenant_id": tenant, "execution_id": exec_id,
           "_skill_obj": _skill_obj(tenant, sid), "cohort_outcomes": _ADVERSE,
           "affected_entity_type": "Candidate", "affected_count": 200}
    result = await ex.execute_skill(_skill_dict(sid), ctx)

    assert result["status"] == "PENDING_HITL"
    assert result["execution_id"] == exec_id
    assert "gender" in result["flagged_attributes"]
    assert ex._exec_engine.ran is False, "the action must not run while paused"

    pending = await hitl_manager.list_pending(tenant)
    assert any(p["exec_id"] == exec_id for p in pending), "no real pending approval created"

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        row = (await db.execute(
            select(SkillExecution).where(SkillExecution.id == exec_id)
        )).scalar_one_or_none()
    assert row is not None and row.status == "PENDING_HITL"


async def test_override_on_resume_clears_finding_and_proceeds(monkeypatch):
    """A pre-approved resume (keyword flag + durable marker) overrides the
    fairness finding and runs the action; the audit row is marked overridden."""
    from app.services.llm_router import LLMRouter
    from app.services.memory.enterprise_memory import EnterpriseMemoryService

    async def boom(self, *a, **k):
        raise AssertionError("statistical path must not consult the LLM")

    async def _no_recall(*a, **k):
        return []

    async def _no_store(*a, **k):
        return None

    monkeypatch.setattr(LLMRouter, "complete", boom)
    monkeypatch.setattr(EnterpriseMemoryService, "recall_similar_situations", _no_recall)
    monkeypatch.setattr(EnterpriseMemoryService, "store_decision_memory", _no_store)
    await init_db()

    tenant = f"tenant_fo_{uuid.uuid4().hex[:6]}"
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    sid = "hr_screen_override"

    ex = AgentExecutor(_FakeCompliance(), _FakeHITL())
    ex._activity_feed = _FakeFeed()
    ex._exec_engine = _FakeExecEngine()

    # The resume carries the durable marker (set by the pause path) + the
    # server-derived approver; hitl_pre_approved is the keyword-only flag.
    ctx = {"tenant_id": tenant, "execution_id": exec_id,
           "_skill_obj": _skill_obj(tenant, sid), "cohort_outcomes": _ADVERSE,
           "affected_entity_type": "Candidate", "affected_count": 200,
           "fairness_review_log_id": "marker-present",
           "has_human_approver": "cfo@acme"}
    result = await ex.execute_skill(_skill_dict(sid), ctx, hitl_pre_approved=True)

    assert result["status"] == "SUCCESS_CLEAN", result
    assert ex._exec_engine.ran is True

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        logs = (await db.execute(
            select(FairnessAuditLog).where(FairnessAuditLog.execution_id == exec_id)
        )).scalars().all()
    assert logs, "resume must still write a fairness audit row"
    assert any(l.was_overridden and l.override_by == "cfo@acme" for l in logs)


async def test_marker_without_keyword_cannot_bypass(monkeypatch):
    """The durable marker in context is not enough on its own: without the
    keyword-only pre-approval flag (which requests cannot set - it is stripped
    from context), the block still routes to HITL rather than auto-clearing."""
    from app.services.llm_router import LLMRouter

    async def boom(self, *a, **k):
        raise AssertionError("statistical path must not consult the LLM")

    monkeypatch.setattr(LLMRouter, "complete", boom)
    await init_db()

    tenant = f"tenant_fx_{uuid.uuid4().hex[:6]}"
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    sid = "hr_screen_smuggle"

    fake_hitl = _FakeHITL()
    ex = AgentExecutor(_FakeCompliance(), fake_hitl)
    ex._activity_feed = _FakeFeed()
    ex._exec_engine = _FakeExecEngine()

    # A request plants BOTH the marker and hitl_pre_approved in context; the
    # keyword flag is stripped at entry, so the skip must not engage.
    ctx = {"tenant_id": tenant, "execution_id": exec_id,
           "_skill_obj": _skill_obj(tenant, sid), "cohort_outcomes": _ADVERSE,
           "affected_entity_type": "Candidate", "affected_count": 200,
           "fairness_review_log_id": "attacker-supplied",
           "hitl_pre_approved": True}
    result = await ex.execute_skill(_skill_dict(sid), ctx)

    assert result["status"] == "PENDING_HITL"
    assert fake_hitl.called is True
    assert ex._exec_engine.ran is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
