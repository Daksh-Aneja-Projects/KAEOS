"""Pipeline smoke test — proves the async compliance gate wiring.

Historically, ``AgentExecutor.execute_skill`` called
``self.compliance.check_before_execution(...)`` WITHOUT awaiting it. Because
``check_before_execution`` is an ``async def``, the un-awaited call returned a
coroutine object, which is always truthy. That made the compliance gate fire on
*every* execution and short-circuit to ``BLOCKED_COMPLIANCE``.

This test drives a clean skill (EEOC-tagged, high confidence, no steps) through
the executor with no LLM API key configured. A correctly wired pipeline must NOT
return ``BLOCKED_COMPLIANCE`` for a benign action.
"""
import pytest

from app.agents.runtime import AgentExecutor
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import HITLManager


@pytest.fixture
def tenant_id() -> str:
    return "tenant-smoke-001"


@pytest.fixture
def skill() -> dict:
    """A benign, high-confidence skill with an EEOC compliance tag and no steps.

    No steps keeps Gate 5 trivial (SUCCESS_CLEAN) so the test stays a true
    unit smoke test with no DB or LLM dependency.
    """
    return {
        "skill_id": "smoke_test_skill",
        "department": "hr",
        "compliance_tags": ["EEOC"],
        "confidence": 0.9,
        "steps": [],
    }


@pytest.fixture
def context(tenant_id: str) -> dict:
    return {
        "tenant_id": tenant_id,
        "execution_id": "exec-smoke-001",
        "intent": "smoke test benign action",
    }


@pytest.mark.asyncio
async def test_benign_skill_is_not_blocked_by_compliance_gate(skill, context, monkeypatch):
    """A benign EEOC-tagged skill must not be BLOCKED_COMPLIANCE with no API key.

    Ensure no provider keys are present so the run exercises the no-key path.
    """
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    executor = AgentExecutor(ComplianceEngine(), HITLManager())
    result = await executor.execute_skill(skill, context)

    assert result["status"] != "BLOCKED_COMPLIANCE", (
        f"benign skill was incorrectly blocked by the compliance gate: {result}"
    )
