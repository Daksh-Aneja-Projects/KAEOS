"""v3 Phase 3 — Cross-Domain Autonomous Missions.

The planner grounds every step in a real ACTIVE skill and orders departments by
canonical priority; high-consequence departments (legal/finance) get a HITL
checkpoint. The engine advances ONE step per call (bounded latency on a real
model; the UI loops), runs each step through the gated executor, honors the budget
gate, HITL approve/reject, and abort — driving the mission ledger. Steps are
independent: an autonomous step runs while another awaits a human, and a single
failure is an exception, not a mission-wide crash. The per-step gate pipeline is
exercised by the runtime suite; here step execution is isolated so the
ORCHESTRATION is tested deterministically.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.domain import Skill
from app.models.missions import MissionStep
from app.services.missions import planner, engine

pytestmark = pytest.mark.asyncio


async def _seed(db, tenant, dept, conf=0.95, skill_id=None):
    sid = skill_id or f"{dept}_skill_{uuid.uuid4().hex[:6]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id=tenant,
                 department=dept, domain=dept, status="ACTIVE", confidence=conf))
    await db.commit()
    return sid


def _fake_exec(monkeypatch, *, status="SUCCESS_CLEAN", cost=0.0):
    async def stub(db, mission, step, execution_id):
        return {"status": status, "steps_completed": 1, "duration_ms": 5,
                "cost": {"total_usd": cost}}
    monkeypatch.setattr(engine, "_execute_step", stub)


async def _drive(db, t, mid, max_steps=25):
    """Call advance repeatedly (as the UI does) until it stops making progress."""
    res = await engine.advance_mission(db, tenant_id=t, mission_id=mid)
    for _ in range(max_steps):
        if res.get("status") != "RUNNING":
            break
        res = await engine.advance_mission(db, tenant_id=t, mission_id=mid)
    return res


async def test_plan_grounds_steps_in_real_skills_and_orders_departments(db):
    t = "tenant_m1"
    await _seed(db, t, "support")
    await _seed(db, t, "finance")
    await _seed(db, t, "legal")

    m = await planner.plan_mission(db, tenant_id=t,
                                   goal="Handle the SEC inquiry, approve the budget, and update support")
    assert m.status == "RUNNING"
    steps = (await db.execute(select(MissionStep).where(MissionStep.mission_id == m.id)
                              .order_by(MissionStep.seq))).scalars().all()
    assert [s.department for s in steps] == ["legal", "finance", "support"]  # canonical order
    assert all(s.skill_id for s in steps)                                    # grounded in real skills
    assert steps[0].hitl_required and steps[1].hitl_required                 # legal + finance high-consequence
    assert all(s.depends_on == [] for s in steps)                           # independent, no invented deps


async def test_empty_tenant_yields_failed_plan(db):
    m = await planner.plan_mission(db, tenant_id="tenant_empty", goal="do something")
    assert m.status == "FAILED"
    assert "No ACTIVE skills" in (m.narrative or "")


async def test_autonomous_steps_run_then_pause_on_hitl_then_complete(db, monkeypatch):
    t = "tenant_m2"
    await _seed(db, t, "finance")   # high-consequence -> hitl
    await _seed(db, t, "support")   # autonomous
    _fake_exec(monkeypatch)

    m = await planner.plan_mission(db, tenant_id=t, goal="close finance then update support")
    res = await _drive(db, t, m.id)
    # Support ran autonomously; finance waits for a human.
    assert res["status"] == "AWAITING_HITL"
    by_dept = {s["department"]: s for s in res["steps"]}
    assert by_dept["support"]["status"] == "DONE"
    assert by_dept["finance"]["status"] == "AWAITING_HITL"

    res2 = await engine.resolve_hitl_step(db, tenant_id=t, mission_id=m.id, seq=1,
                                          approved=True, approver="cfo")
    res2 = await _drive(db, t, m.id)
    assert res2["status"] == "COMPLETED"
    assert all(s["status"] == "DONE" for s in res2["steps"])


async def test_hitl_rejection_skips_step_but_others_complete(db, monkeypatch):
    t = "tenant_m3"
    await _seed(db, t, "legal")     # hitl
    await _seed(db, t, "support")   # autonomous
    _fake_exec(monkeypatch)

    m = await planner.plan_mission(db, tenant_id=t, goal="legal review and support update")
    await _drive(db, t, m.id)       # support done, legal awaiting
    res = await engine.resolve_hitl_step(db, tenant_id=t, mission_id=m.id, seq=1,
                                         approved=False, approver="counsel")
    assert res["status"] == "COMPLETED_WITH_EXCEPTIONS"
    by_dept = {s["department"]: s for s in res["steps"]}
    assert by_dept["legal"]["status"] == "SKIPPED"
    assert by_dept["support"]["status"] == "DONE"


async def test_budget_gate_blocks_before_overspend(db, monkeypatch):
    t = "tenant_m4"
    await _seed(db, t, "support")   # autonomous, no hitl
    _fake_exec(monkeypatch, cost=1.0)

    m = await planner.plan_mission(db, tenant_id=t, goal="update support tickets", budget_usd=0.0)
    res = await engine.advance_mission(db, tenant_id=t, mission_id=m.id)
    assert res["status"] == "BUDGET_BLOCKED"
    assert res["steps"][0]["status"] in ("PENDING", "READY")


async def test_autonomous_mission_runs_to_completion(db, monkeypatch):
    t = "tenant_m5"
    await _seed(db, t, "support")
    await _seed(db, t, "sales")
    _fake_exec(monkeypatch, cost=0.01)

    m = await planner.plan_mission(db, tenant_id=t, goal="update support and sales pipeline")
    res = await _drive(db, t, m.id)
    assert res["status"] == "COMPLETED"
    assert res["spent_usd"] == pytest.approx(0.02)
    assert all(s["status"] == "DONE" for s in res["steps"])


async def test_compliance_block_on_autonomous_step_escalates_to_human(db, monkeypatch):
    """A compliance block on an autonomous step escalates to a HITL checkpoint
    (not a hard failure); approval re-runs it to completion."""
    t = "tenant_m7"
    await _seed(db, t, "support")   # autonomous (not high-consequence)

    calls = {"n": 0}

    async def stub(db_, mission, step, execution_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "BLOCKED_COMPLIANCE",
                    "violations": [{"reason": "SOX requires explicit human approval"}]}
        return {"status": "SUCCESS_CLEAN", "steps_completed": 1, "duration_ms": 3, "cost": {"total_usd": 0.0}}

    monkeypatch.setattr(engine, "_execute_step", stub)

    m = await planner.plan_mission(db, tenant_id=t, goal="update support tickets")
    res = await _drive(db, t, m.id)
    assert res["status"] == "AWAITING_HITL"
    assert res["steps"][0]["status"] == "AWAITING_HITL"
    assert res["steps"][0]["hitl_required"] is True  # escalated

    await engine.resolve_hitl_step(db, tenant_id=t, mission_id=m.id, seq=1,
                                   approved=True, approver="compliance_officer")
    res2 = await _drive(db, t, m.id)
    assert res2["status"] == "COMPLETED"
    assert res2["steps"][0]["status"] == "DONE"


async def test_failed_step_is_an_exception_not_a_crash(db, monkeypatch):
    t = "tenant_m8"
    await _seed(db, t, "support")   # will fail
    await _seed(db, t, "sales")     # will succeed

    async def stub(db_, mission, step, execution_id):
        if step.department == "support":
            return {"status": "FAILED_AUDIT", "reason": "missing audit datum"}
        return {"status": "SUCCESS_CLEAN", "steps_completed": 1, "duration_ms": 2, "cost": {"total_usd": 0.0}}

    monkeypatch.setattr(engine, "_execute_step", stub)
    m = await planner.plan_mission(db, tenant_id=t, goal="update support and sales")
    res = await _drive(db, t, m.id)
    assert res["status"] == "COMPLETED_WITH_EXCEPTIONS"
    by_dept = {s["department"]: s for s in res["steps"]}
    assert by_dept["support"]["status"] == "FAILED"
    assert by_dept["sales"]["status"] == "DONE"


async def test_abort_marks_skipped(db, monkeypatch):
    t = "tenant_m6"
    await _seed(db, t, "support")
    _fake_exec(monkeypatch)
    m = await planner.plan_mission(db, tenant_id=t, goal="support update")
    res = await engine.abort_mission(db, tenant_id=t, mission_id=m.id, actor="ops")
    assert res["status"] == "ABORTED"
    assert res["steps"][0]["status"] == "SKIPPED"
