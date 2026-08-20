"""S5 M6.1 - the gate pipeline must not hold the caller's DB connection.

A department endpoint used to enter AgentExecutor.execute_skill with its
request session's read transaction still open, pinning one pooled connection
for the whole multi-LLM pipeline (240s LLM timeout; pool 15/worker -> ~15
concurrent governed runs exhausted a worker). execute_skill now commits the
request session (published via current_request_db) before Gate 1, and the
mission engine ends its own read transaction before handing off.

The probe compliance engine below runs INSIDE Gate 1 and records whether the
request session still holds a transaction - exactly the thing the fix ends.
It then blocks, so the test never needs a model call.
"""
import asyncio
import uuid

from app.agents.runtime import AgentExecutor
from app.core.context import current_request_db
from app.services.hitl_manager import hitl_manager
from tests.conftest import TestingSessionLocal


class _ProbeCompliance:
    """Stands in for ComplianceEngine; observes the session state at Gate 1."""

    def __init__(self):
        self.saw_open_transaction = None

    async def check_before_execution(self, tags, context):
        sess = current_request_db.get()
        self.saw_open_transaction = bool(sess is not None and sess.in_transaction())
        return [{"severity": "BLOCKER", "reason": "probe stop"}]


def _skill():
    return {"skill_id": f"probe.{uuid.uuid4().hex[:6]}", "department": "operations",
            "steps": [{"id": "s1", "action": "noop"}], "compliance_tags": ["SOX"],
            "confidence": 0.9}


async def _run_with_request_session():
    from sqlalchemy import text

    probe = _ProbeCompliance()
    executor = AgentExecutor(probe, hitl_manager)
    async with TestingSessionLocal() as sess:
        await sess.execute(text("SELECT 1"))          # open a read transaction
        assert sess.in_transaction()
        token = current_request_db.set(sess)          # what get_db now publishes
        try:
            result = await executor.execute_skill(
                _skill(), {"tenant_id": f"t_{uuid.uuid4().hex[:6]}"})
        finally:
            current_request_db.reset(token)
        # The session must remain usable after the pipeline's commit.
        assert (await sess.execute(text("SELECT 2"))).scalar() == 2
    return probe, result


def test_gate_pipeline_releases_the_request_transaction():
    probe, result = asyncio.run(_run_with_request_session())
    assert result["status"] == "BLOCKED_COMPLIANCE"   # the probe actually ran
    assert probe.saw_open_transaction is False, (
        "Gate 1 observed the request session still inside a transaction - the "
        "pooled connection would be held across the whole LLM pipeline")


async def _run_without_request_session():
    probe = _ProbeCompliance()
    executor = AgentExecutor(probe, hitl_manager)
    result = await executor.execute_skill(
        _skill(), {"tenant_id": f"t_{uuid.uuid4().hex[:6]}"})
    return probe, result


def test_background_callers_without_a_request_session_are_untouched():
    probe, result = asyncio.run(_run_without_request_session())
    assert result["status"] == "BLOCKED_COMPLIANCE"
    assert probe.saw_open_transaction is False       # None session -> guard no-ops
