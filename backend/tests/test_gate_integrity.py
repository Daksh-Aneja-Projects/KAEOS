"""Regression tests for the three gate-pipeline integrity defects.

1.1  A hitl_required mission step with NO persisted approval record must never
     execute: it returns PENDING_HITL and re-gates, even if its status invariant
     (READY only via human approval) was somehow broken. The pre-approval flags
     are derived from the approval record (approver + timestamp), never from
     the hitl_required requirement itself.

1.2  Gate 3 fails CLOSED: when the tenant confidence-ceiling lookup throws
     (Redis/DB failure, cold cache), the FAILSAFE_CONFIDENCE_CEILING is applied
     instead of no cap, so the decision routes to a human rather than letting
     the skill's raw declared confidence grant autonomy.

1.3  hitl_pre_approved is trust-bearing and keyword-only: values planted in a
     (potentially request-controlled) context dict are stripped and ignored, at
     the executor and at the /skills/{id}/execute API boundary.
"""
import asyncio
import uuid

import pytest

from app.agents.runtime import AgentExecutor
from app.models.domain import Skill
from app.models.missions import Mission, MissionStep
from app.services.missions import engine


# ── Shared fakes (same shape as test_gate3_byok_ceiling) ─────────────────

class _FakeHITL:
    def __init__(self):
        self.called = False

    async def request_human_confirmation(self, skill, context):
        self.called = True
        return {"pending": True, "execution_id": context.get("execution_id", "x")}


class _FakeCompliance:
    async def check_before_execution(self, tags, context):
        return []

    def enforce_audit_requirements(self, *a, **k):
        return True


class _FakeRouter:
    def __init__(self, ceiling):
        self._ceiling = ceiling

    def confidence_ceiling(self, model_tier="reasoning"):
        return self._ceiling


class _FakeExecEngine:
    def __init__(self):
        self.ran = False

    async def run(self, skill, context, execution_id, tenant_id, skill_obj=None,
                  compliance_warnings=None):
        self.ran = True
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [], "execution_id": execution_id,
                "steps_completed": 1, "duration_ms": 1, "skill_id": skill.get("skill_id")}


class _FakeFeed:
    async def emit(self, **kwargs):
        return None


def _executor(monkeypatch, ceiling=1.0):
    from app.services import llm_router as lr

    async def fake_for_tenant(cls, tenant_id):
        return _FakeRouter(ceiling)

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(fake_for_tenant))
    ex = AgentExecutor(_FakeCompliance(), _FakeHITL())
    ex._exec_engine = _FakeExecEngine()
    ex._activity_feed = _FakeFeed()
    return ex


# ── Mission fixtures ─────────────────────────────────────────────────────

async def _seed_skill(db, tenant, dept="finance"):
    sid = f"{dept}_skill_{uuid.uuid4().hex[:6]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id=tenant,
                 department=dept, domain=dept, status="ACTIVE", confidence=0.95))
    await db.commit()
    return sid


async def _mk_mission(db, tenant, skill_id, *, step_status, hitl_required=True):
    mission = Mission(tenant_id=tenant, goal="test goal", status="RUNNING")
    db.add(mission)
    await db.flush()
    step = MissionStep(tenant_id=tenant, mission_id=mission.id, seq=1,
                       name="gated step", department="finance", skill_id=skill_id,
                       confidence=0.95, hitl_required=hitl_required, status=step_status)
    db.add(step)
    await db.commit()
    return mission, step


# ── 1.1: approval record is the source of truth ──────────────────────────

async def test_hitl_step_without_approval_record_does_not_execute(db, monkeypatch):
    """Even a READY hitl_required step (broken invariant) must not execute
    without a persisted approval record: PENDING_HITL, executor never called."""
    t = "tenant_gate11a"
    sid = await _seed_skill(db, t)
    mission, step = await _mk_mission(db, t, sid, step_status="READY")

    called = {}

    async def spy(self, skill, context, *, hitl_pre_approved=False):
        called["executed"] = True
        return {"status": "SUCCESS_CLEAN", "steps_completed": 1, "duration_ms": 1}

    monkeypatch.setattr(AgentExecutor, "execute_skill", spy)

    res = await engine._execute_step(db, mission, step, "exec-gate11a")
    assert res["status"] == "PENDING_HITL"
    assert "executed" not in called, "hitl_required step ran without an approval record"


async def test_unapproved_hitl_step_regates_via_advance_mission(db, monkeypatch):
    """Full engine pass: the guarded step folds back to AWAITING_HITL."""
    t = "tenant_gate11b"
    sid = await _seed_skill(db, t)
    mission, step = await _mk_mission(db, t, sid, step_status="READY")

    async def spy(self, skill, context, *, hitl_pre_approved=False):
        raise AssertionError("executor must not run")

    monkeypatch.setattr(AgentExecutor, "execute_skill", spy)

    res = await engine.advance_mission(db, tenant_id=t, mission_id=mission.id)
    by_seq = {s["seq"]: s for s in res["steps"]}
    assert by_seq[1]["status"] == "AWAITING_HITL"
    assert res["status"] == "AWAITING_HITL"


async def test_approval_record_written_and_flags_derived_from_it(db, monkeypatch):
    """resolve_hitl_step persists approver + timestamp; the executor then runs
    with hitl_pre_approved=True (keyword) and the REAL approver identity in
    has_human_approver - and no hitl_pre_approved key inside the context."""
    t = "tenant_gate11c"
    sid = await _seed_skill(db, t)
    mission, step = await _mk_mission(db, t, sid, step_status="AWAITING_HITL")

    await engine.resolve_hitl_step(db, tenant_id=t, mission_id=mission.id, seq=1,
                                   approved=True, approver="cfo@acme")
    await db.refresh(step)
    assert step.approved_by == "cfo@acme"
    assert step.approved_at is not None
    assert step.status == "READY"

    captured = {}

    async def spy(self, skill, context, *, hitl_pre_approved=False):
        captured["pre_approved"] = hitl_pre_approved
        captured["context"] = context
        return {"status": "SUCCESS_CLEAN", "steps_completed": 1, "duration_ms": 1}

    monkeypatch.setattr(AgentExecutor, "execute_skill", spy)

    res = await engine._execute_step(db, mission, step, "exec-gate11c")
    assert res["status"] == "SUCCESS_CLEAN"
    assert captured["pre_approved"] is True
    assert captured["context"]["has_human_approver"] == "cfo@acme"
    assert "hitl_pre_approved" not in captured["context"]


# ── 1.2: Gate 3 fails closed on ceiling-lookup failure ───────────────────

def test_gate3_ceiling_lookup_failure_fails_closed(monkeypatch):
    from app.services import llm_router as lr

    async def boom(cls, tenant_id):
        raise RuntimeError("redis unreachable")

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(boom))
    ex = AgentExecutor(_FakeCompliance(), _FakeHITL())
    ex._exec_engine = _FakeExecEngine()
    ex._activity_feed = _FakeFeed()

    skill = {"skill_id": "confident_skill", "confidence": 0.95,
             "steps": [{"step": 1, "name": "Do", "prompt": "do the thing"}],
             "compliance_tags": []}
    out = asyncio.run(ex.execute_skill(skill, {"tenant_id": "t", "execution_id": "e-fc"}))
    assert out["status"] == "PENDING_HITL", \
        "a failed ceiling lookup must route to a human, not grant raw confidence"
    assert ex.hitl.called is True
    assert ex._exec_engine.ran is False


# ── 1.3: pre-approval cannot be smuggled through context ─────────────────

def test_context_smuggled_pre_approval_ignored_low_confidence(monkeypatch):
    ex = _executor(monkeypatch, ceiling=1.0)
    skill = {"skill_id": "low_conf_skill", "confidence": 0.10,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    ctx = {"tenant_id": "t", "execution_id": "e-sm1", "hitl_pre_approved": True}
    out = asyncio.run(ex.execute_skill(skill, ctx))
    assert out["status"] == "PENDING_HITL"
    assert ex._exec_engine.ran is False


def test_context_smuggled_pre_approval_ignored_high_consequence(monkeypatch):
    ex = _executor(monkeypatch, ceiling=1.0)
    skill = {"skill_id": "wire_transfer_approve", "confidence": 0.99,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    ctx = {"tenant_id": "t", "execution_id": "e-sm2", "hitl_pre_approved": True}
    out = asyncio.run(ex.execute_skill(skill, ctx))
    assert out["status"] == "PENDING_HITL"
    assert ex._exec_engine.ran is False


def test_keyword_pre_approval_is_honored(monkeypatch):
    """The legitimate mission-engine path: the keyword argument (backed by a
    persisted approval record) does clear Gate 3."""
    ex = _executor(monkeypatch, ceiling=1.0)
    skill = {"skill_id": "wire_transfer_approve", "confidence": 0.99,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    ctx = {"tenant_id": "t", "execution_id": "e-kw"}
    out = asyncio.run(ex.execute_skill(skill, ctx, hitl_pre_approved=True))
    assert out["status"] == "SUCCESS_CLEAN"
    assert ex._exec_engine.ran is True


async def test_api_request_context_cannot_smuggle_pre_approval(db, async_client, monkeypatch):
    """POST /skills/{id}/execute with hitl_pre_approved planted in body.context:
    a low-confidence skill and a high-consequence skill must both still gate."""
    from app.services import llm_router as lr

    async def fake_for_tenant(cls, tenant_id):
        return _FakeRouter(1.0)

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(fake_for_tenant))

    # The route runs the full pipeline now; the Gate-3 pause emits to the
    # activity feed, whose table lives on the app engine this module never
    # initializes. The feed is not under test - mute it.
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)

    tenant = "tenant_acme"  # DEV_MODE middleware tenant
    low_id = f"low_conf_{uuid.uuid4().hex[:6]}"
    high_id = f"wire_transfer_approve_{uuid.uuid4().hex[:6]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=low_id, tenant_id=tenant,
                 department="support", domain="support", status="ACTIVE", confidence=0.20))
    db.add(Skill(id=str(uuid.uuid4()), skill_id=high_id, tenant_id=tenant,
                 department="finance", domain="finance", status="ACTIVE", confidence=0.99))
    await db.commit()

    payload = {"intent": "run it",
               "context": {"hitl_pre_approved": True, "has_human_approver": True}}

    r1 = await async_client.post(f"/api/v1/skills/{low_id}/execute", json=payload)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "PENDING_HITL"

    r2 = await async_client.post(f"/api/v1/skills/{high_id}/execute", json=payload)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "PENDING_HITL"


async def test_skills_route_runs_the_one_pipeline(db, async_client, monkeypatch):
    """Regression lock for the collapsed execution paths: /skills/{id}/execute
    (which the MCP execute_skill tool forwards to) must run
    AgentExecutor.execute_skill - the ONE pipeline - not a partial inline
    re-implementation that skips Fairness/Debate."""
    from app.agents.runtime import AgentExecutor

    seen = {}

    async def spy(self, skill, context, *, hitl_pre_approved=False):
        seen["skill"] = skill
        seen["pre_approved"] = hitl_pre_approved
        seen["has_skill_obj"] = context.get("_skill_obj") is not None
        return {"status": "SUCCESS_CLEAN", "execution_id": context.get("execution_id"),
                "reasoning_chain": [], "steps_completed": 0, "duration_ms": 1}

    monkeypatch.setattr(AgentExecutor, "execute_skill", spy)

    tenant = "tenant_acme"
    sid = f"pipeline_lock_{uuid.uuid4().hex[:6]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id=tenant,
                 department="support", domain="support", status="ACTIVE",
                 confidence=0.95))
    await db.commit()

    r = await async_client.post(f"/api/v1/skills/{sid}/execute",
                                json={"intent": "run", "context": {}})
    assert r.status_code == 200, r.text
    assert seen["skill"]["skill_id"] == sid
    assert seen["skill"]["skill_db_id"], "pause-resume needs the compiled Skill id"
    assert seen["pre_approved"] is False, "a route call is never pre-approved"
    assert seen["has_skill_obj"], "fairness/debate gates need the ORM skill"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
