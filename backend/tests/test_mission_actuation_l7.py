"""L7 closed loop — a human-approved mission step with an actuation intent must
pass that intent to the runtime so Gate 5b performs the governed write.

We capture the skill_dict handed to the executor (the exact hand-off that Gate 5b
reads `actuation` from) rather than running the full DB/gate pipeline, so the test
is deterministic and isolates the loop-closing decision.
"""
import uuid


import app.agents.runtime as runtime_mod
from app.services.missions import engine as mission_engine
from app.models.domain import Skill
from app.models.missions import Mission, MissionStep


T = "tenant_l7"
_ACT = {"system": "sandbox", "object_type": "record", "external_id": "emp_42",
        "operation": "UPDATE", "payload": {"status": "onboarded"}}


async def _make_skill(db):
    s = Skill(id=str(uuid.uuid4()), skill_id="ops_action", tenant_id=T,
              department="operations", domain="operations", status="ACTIVE", confidence=0.9)
    db.add(s)
    await db.commit()
    return s


def _step(hitl, actuation):
    return MissionStep(id=str(uuid.uuid4()), tenant_id=T, mission_id="m1", seq=1,
                       name="do_it", department="operations", skill_id="ops_action",
                       confidence=0.9, hitl_required=hitl, actuation=actuation, status="READY")


async def _capture_skill_dict(db, monkeypatch, step):
    captured = {}

    async def fake_execute_skill(self, skill_dict, ctx):
        captured["skill_dict"] = skill_dict
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [{"decision": "done"}],
                "steps_completed": 1, "duration_ms": 1}

    monkeypatch.setattr(runtime_mod.AgentExecutor, "execute_skill", fake_execute_skill)
    mission = Mission(id="m1", tenant_id=T, goal="onboard the new hire", status="RUNNING")
    await mission_engine._execute_step(db, mission, step, execution_id="exec-1")
    return captured["skill_dict"]


async def test_human_approved_step_with_intent_actuates(db, monkeypatch):
    await _make_skill(db)
    skill_dict = await _capture_skill_dict(db, monkeypatch, _step(hitl=True, actuation=_ACT))
    # The actuation intent is handed to the runtime -> Gate 5b will fire.
    assert skill_dict.get("actuation") == _ACT


async def test_advisory_step_without_intent_does_not_actuate(db, monkeypatch):
    await _make_skill(db)
    skill_dict = await _capture_skill_dict(db, monkeypatch, _step(hitl=True, actuation=None))
    assert "actuation" not in skill_dict


async def test_intent_without_human_approval_does_not_actuate(db, monkeypatch):
    # An actuation intent present but NOT human-approved must stay advisory.
    await _make_skill(db)
    skill_dict = await _capture_skill_dict(db, monkeypatch, _step(hitl=False, actuation=_ACT))
    assert "actuation" not in skill_dict
