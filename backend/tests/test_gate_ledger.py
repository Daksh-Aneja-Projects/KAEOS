"""H9: the provenance ledger records refusals, not only successes.

Gates 1-4 stop the pipeline before the executor runs, so skill_executor's Gate-5
ledger write never fired for them — a refused execution left a SkillExecution row
but no hash-chained proof, while the product's compliance claim is 'we prove what
we refused'. _ledger_gate_stop now hash-chains those refusals, and self-filters so
executor outcomes (already ledgered) are not double-counted."""
import pytest
from sqlalchemy import func, select

from app.agents.runtime import AgentExecutor
from app.core.database import AsyncSessionLocal
from app.models.domain import ProvenanceLedger
from app.models.execution_status import ExecutionStatus
from app.services.compliance import ComplianceEngine


class _SkillObj:
    id = "skill-h9-123"


async def _count(tenant, event_type):
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            select(func.count()).select_from(ProvenanceLedger).where(
                ProvenanceLedger.tenant_id == tenant,
                ProvenanceLedger.event_type == event_type))).scalar()


@pytest.mark.asyncio
async def test_gate_refusal_is_hash_chained():
    ex = AgentExecutor(ComplianceEngine(), None)
    ctx = {"execution_id": "e-h9", "tenant_id": "tenant_h9"}
    await ex._ledger_gate_stop(
        _SkillObj(), ctx,
        {"status": ExecutionStatus.BLOCKED_COMPLIANCE, "reason": "no lawful basis"})
    assert await _count("tenant_h9", "GATE_REFUSAL") == 1


@pytest.mark.asyncio
async def test_executor_outcome_is_not_double_ledgered():
    ex = AgentExecutor(ComplianceEngine(), None)
    ctx = {"execution_id": "e-h9b", "tenant_id": "tenant_h9b"}
    # SUCCESS_CLEAN went through the executor, which already ledgered it.
    await ex._ledger_gate_stop(
        _SkillObj(), ctx, {"status": ExecutionStatus.SUCCESS_CLEAN})
    # BLOCKED_ACTUATION is Gate 5b (post-executor) — also already ledgered.
    await ex._ledger_gate_stop(
        _SkillObj(), ctx, {"status": ExecutionStatus.BLOCKED_ACTUATION})
    assert await _count("tenant_h9b", "GATE_REFUSAL") == 0


@pytest.mark.asyncio
async def test_synthetic_skill_without_obj_is_a_noop():
    ex = AgentExecutor(ComplianceEngine(), None)
    ctx = {"execution_id": "e-h9c", "tenant_id": "tenant_h9c"}
    await ex._ledger_gate_stop(
        None, ctx, {"status": ExecutionStatus.PENDING_HITL})
    assert await _count("tenant_h9c", "GATE_REFUSAL") == 0
