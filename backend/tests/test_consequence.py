"""Regression tests for explicit high-consequence detection (always_hitl).

The always-route-to-a-human guarantee previously depended on substring matching
over tags/department/skill_id, duplicated in two files: renaming
wire_transfer_approve to treasury_settle silently made it autonomous. The
explicit Skill.always_hitl flag is now authoritative via the single shared
helper app/services/consequence.py; tag inference remains as an escalate-only
fallback.
"""
import asyncio
import uuid

import pytest

from app.models.domain import Skill
from app.services.consequence import is_high_consequence

from tests.test_gate_integrity import (  # shared gate fakes
    _FakeRouter, _executor,
)


# ── Helper semantics ─────────────────────────────────────────────────────

def test_explicit_flag_forces_high_consequence_despite_innocuous_name():
    assert is_high_consequence({"skill_id": "treasury_settle", "always_hitl": True,
                                "compliance_tags": [], "department": "finance"}) is True


def test_explicit_flag_works_on_orm_skill():
    s = Skill(skill_id="treasury_settle", tenant_id="t", department="finance",
              always_hitl=True)
    assert is_high_consequence(s) is True


def test_tag_inference_is_escalate_only_fallback():
    # Inference still catches convention-named skills without the flag...
    assert is_high_consequence({"skill_id": "wire_transfer_approve",
                                "always_hitl": False}) is True
    # ...but an innocuously named, unflagged skill is not high-consequence.
    assert is_high_consequence({"skill_id": "summarize_notes",
                                "always_hitl": False}) is False


def test_none_and_empty_are_not_high_consequence():
    assert is_high_consequence(None) is False
    assert is_high_consequence({}) is False


# ── Gate 3 (runtime) enforcement ─────────────────────────────────────────

def test_gate3_routes_flagged_skill_with_innocuous_name_to_human(monkeypatch):
    ex = _executor(monkeypatch, ceiling=1.0)
    skill = {"skill_id": "treasury_settle", "confidence": 0.99, "always_hitl": True,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    out = asyncio.run(ex.execute_skill(skill, {"tenant_id": "t", "execution_id": "e-ah1"}))
    assert out["status"] == "PENDING_HITL", \
        "explicitly flagged skill must route to a human even with no tag-matching name"
    assert ex._exec_engine.ran is False


def test_gate3_reads_flag_from_persisted_skill_obj(monkeypatch):
    """The executor's skill dict may not carry the flag; the ORM row in
    context._skill_obj must still force HITL."""
    ex = _executor(monkeypatch, ceiling=1.0)
    skill_obj = Skill(skill_id="treasury_settle", tenant_id="t", department="general",
                      always_hitl=True, confidence=0.99, execution_count=0, success_rate=0.0)
    skill = {"skill_id": "treasury_settle", "confidence": 0.99,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    ctx = {"tenant_id": "t", "execution_id": "e-ah2", "_skill_obj": skill_obj}
    # Fairness/debate gates receive a synthetic Skill; neither engages for a
    # non-people-facing general skill, so the run reaches Gate 3.
    out = asyncio.run(ex.execute_skill(skill, ctx))
    assert out["status"] == "PENDING_HITL"
    assert ex._exec_engine.ran is False


def test_gate3_unflagged_innocuous_skill_still_autonomous(monkeypatch):
    """Control: the explicit flag must not over-trigger."""
    ex = _executor(monkeypatch, ceiling=1.0)
    skill = {"skill_id": "summarize_notes", "confidence": 0.95,
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}], "compliance_tags": []}
    out = asyncio.run(ex.execute_skill(skill, {"tenant_id": "t", "execution_id": "e-ah3"}))
    assert out["status"] == "SUCCESS_CLEAN"


# ── Direct /skills execute route enforcement ─────────────────────────────

async def test_api_flagged_skill_with_innocuous_name_gates(db, async_client, monkeypatch):
    from app.services import llm_router as lr

    async def fake_for_tenant(cls, tenant_id):
        return _FakeRouter(1.0)

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(fake_for_tenant))

    sid = f"treasury_settle_{uuid.uuid4().hex[:6]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id="tenant_acme",
                 department="general", domain="general", status="ACTIVE",
                 confidence=0.99, always_hitl=True))
    await db.commit()

    r = await async_client.post(f"/api/v1/skills/{sid}/execute",
                                json={"intent": "settle", "context": {}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PENDING_HITL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
