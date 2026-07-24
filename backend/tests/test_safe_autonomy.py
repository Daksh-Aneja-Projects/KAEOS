"""
Phase 5 - safe-autonomy-rate is computed from real logged executions.

Seeds skill_executions with a known mix and asserts the rate and the explainable
fallout breakdown reconcile exactly. Nothing is estimated or seeded into the
metric itself.
"""
import uuid

import pytest

from app.models.domain import SkillExecution
from app.services.safe_autonomy import compute_safe_autonomy

pytestmark = pytest.mark.asyncio


async def _exec(db, tenant, skill, *, hitl_required, status, outcome_type="SUCCESS_CLEAN"):
    row = SkillExecution(
        id=str(uuid.uuid4()),
        skill_id_name=skill,
        tenant_id=tenant,
        status=status,
        hitl_required=hitl_required,
        outcome_type=outcome_type,
    )
    db.add(row)
    await db.commit()


async def test_safe_autonomy_rate_and_breakdown(db):
    t = "tenant_sar"
    # 6 executions: 3 safe-autonomous, 1 routed to human, 1 overridden, 1 failed.
    await _exec(db, t, "refund", hitl_required=False, status="SUCCESS_CLEAN")
    await _exec(db, t, "refund", hitl_required=False, status="SUCCESS_CLEAN")
    await _exec(db, t, "triage", hitl_required=False, status="SUCCESS_CLEAN")
    await _exec(db, t, "payout", hitl_required=True, status="SUCCESS_CLEAN")
    await _exec(db, t, "triage", hitl_required=False, status="HUMAN_OVERRIDDEN")
    await _exec(db, t, "refund", hitl_required=False, status="FAILED_RULE_MISMATCH")

    result = await compute_safe_autonomy(db, t, days=30)

    assert result["total_executions"] == 6
    assert result["safe_autonomous"] == 3
    assert result["safe_autonomy_rate"] == 0.5
    assert result["fallout"]["routed_to_human"] == 1
    assert result["fallout"]["human_overridden"] == 1
    assert result["fallout"]["failed"] == 1

    # Per-skill split present and refund shows 2/3 safe.
    refund = next(s for s in result["by_skill"] if s["skill"] == "refund")
    assert refund["total"] == 3
    assert refund["safe_autonomy_rate"] == round(2 / 3, 4)


async def test_empty_tenant_returns_null_rate(db):
    result = await compute_safe_autonomy(db, "tenant_nobody", days=30)
    assert result["total_executions"] == 0
    assert result["safe_autonomy_rate"] is None
