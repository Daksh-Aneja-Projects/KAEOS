"""
Regression: the BYOK tenant model ceiling must gate DOMAIN AGENTS, not just
the /skills routes.

Gate 3 previously compared the skill's static confidence (0.85 in most gated
runners) against 0.82 without consulting the tenant's probed tier_ceiling -
so a tenant running a weak model got full autonomy on finance/legal/support
actions. Gate 3 now caps confidence with LLMRouter.for_tenant(...).ceiling.
"""
import asyncio

import pytest

from app.agents.runtime import AgentExecutor


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


def _executor(monkeypatch, ceiling):
    from app.services import llm_router as lr

    async def fake_for_tenant(cls, tenant_id):
        return _FakeRouter(ceiling)

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(fake_for_tenant))
    ex = AgentExecutor(_FakeCompliance(), _FakeHITL())
    ex._exec_engine = _FakeExecEngine()
    return ex


SKILL = {"skill_id": "byok_gate3_test", "confidence": 0.85,
         "steps": [{"step": 1, "name": "Do", "prompt": "do the thing"}],
         "compliance_tags": []}


def test_weak_model_ceiling_forces_hitl(monkeypatch):
    ex = _executor(monkeypatch, ceiling=0.70)
    out = asyncio.run(ex.execute_skill(dict(SKILL), {"tenant_id": "t", "execution_id": "e1"}))
    assert out["status"] == "PENDING_HITL", \
        "confidence 0.85 capped to 0.70 must pause for a human"
    assert ex.hitl.called is True


def test_strong_model_ceiling_proceeds(monkeypatch):
    ex = _executor(monkeypatch, ceiling=1.0)
    out = asyncio.run(ex.execute_skill(dict(SKILL), {"tenant_id": "t", "execution_id": "e2"}))
    assert out["status"] == "SUCCESS_CLEAN"
    assert ex._exec_engine.ran is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
