"""Three untested statutory invariants (§05 gap-hunt).

1. Mission Gate 5b BLOCKED_ACTUATION: a governed write to a FINANCE system of
   record is re-gated against SOX four-eyes right before it lands; a blocker
   refuses the write (fail-closed) and rewrites the persisted execution row to a
   failure status, so a blocked money-move can never score as safe autonomy.
2. ECOA/Reg B: an adverse-action notice sent >30 days after the decision BLOCKS;
   within 30 days PASSES.
3. HIPAA 42 CFR Part 2: an SUD disclosure with no matching stored consent BLOCKS;
   with a valid stored Part-2 consent PASSES.

These fail loudly if the corresponding guard is removed.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.compliance.registry import run_checks
from app.healthcare.services.phi_disclosure import resolve_consent_facts


# ── (2) ECOA >30-day adverse-action notice ──────────────────────────────────
def _ecoa_ctx(notice_days):
    # decision=DENY makes the checker applicable; a single specific principal
    # reason and no prohibited basis isolate notice timing as the only variable.
    return {
        "decision": "DENY",
        "adverse_action": {
            "reasons": ["Debt-to-income ratio of 62% exceeds the 45% program limit"],
            "notice_days": notice_days,
            "prohibited_basis_used": False,
        },
    }


def test_ecoa_notice_over_30_days_blocks():
    late = run_checks(["ECOA"], _ecoa_ctx(45))
    assert not late["verified"], "a 45-day-late adverse-action notice must BLOCK"
    assert any(b["framework"] == "ECOA" for b in late["blocking"])


def test_ecoa_notice_within_30_days_passes():
    ok = run_checks(["ECOA"], _ecoa_ctx(30))
    assert ok["verified"], "a 30-day notice (with a specific reason) must PASS"


# ── (3) HIPAA 42 CFR Part 2 SUD consent ─────────────────────────────────────
def _part2_ctx(stored_consents):
    facts = resolve_consent_facts(
        purpose="treatment",
        stored_diagnosis_codes=["F10.20"],  # alcohol use disorder -> Part 2
        stored_consents=stored_consents,
    )
    return {
        "part2_records": True,
        "part2_consent": facts["part2_consent"],
        "diagnosis_codes": facts["diagnosis_codes"],
    }


def test_part2_disclosure_without_stored_consent_blocks():
    verdict = run_checks(["PART2"], _part2_ctx(stored_consents=[]))
    assert not verdict["verified"], "SUD disclosure with no stored consent must BLOCK"
    assert any(b["framework"] == "PART2" for b in verdict["blocking"])


def test_part2_disclosure_with_valid_stored_consent_passes():
    verdict = run_checks(["PART2"], _part2_ctx(
        stored_consents=[{"scope": "part2", "part2": True, "active": True}]))
    assert verdict["verified"], "SUD disclosure with a valid stored Part-2 consent must PASS"


# ── (1) Mission Gate 5b: BLOCKED_ACTUATION on a FINANCE write ────────────────
def test_gate5b_finance_write_blocked_by_sox(monkeypatch):
    """An approved, executed skill declares an actuation write to a FINANCE SoR.
    Gate 5b re-gates the untagged write, the finance fallback applies SOX, and
    four-eyes is unverifiable (no attributable maker/approver) -> BLOCKED_ACTUATION,
    and the persisted SkillExecution row is rewritten to a failure state."""
    from app.agents.runtime import AgentExecutor
    from app.services.compliance import ComplianceEngine
    from app.services.activity_feed import ActivityFeedService
    from app.services.memory.enterprise_memory import EnterpriseMemoryService
    import app.services.skill_executor as skill_executor
    from app.core.database import AsyncSessionLocal
    from app.models.domain import SkillExecution

    # Side channels not under test: silence the feed (its notifier opens a
    # concurrent session on the StaticPool connection) and the memory recall
    # (embeds via the real local model).
    async def _noop(self, **kwargs):
        return None

    async def _no_recall(*a, **k):
        return []

    async def _no_store(*a, **k):
        return None

    async def _fake_run(self, **kwargs):
        # Stand in for the real generative execution: the skill "succeeded",
        # so only Gate 5b's re-gate decides whether the world gets changed.
        return {"status": "SUCCESS_CLEAN", "steps_completed": 1, "duration_ms": 1,
                "reasoning_chain": [{"decision": "post the entry"}], "cost": None}

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)
    monkeypatch.setattr(EnterpriseMemoryService, "recall_similar_situations", _no_recall)
    monkeypatch.setattr(EnterpriseMemoryService, "store_decision_memory", _no_store)
    monkeypatch.setattr(skill_executor.SkillExecutionEngine, "run", _fake_run)

    t = f"tenant_g5b_{uuid.uuid4().hex[:6]}"
    exec_id = f"exec-{uuid.uuid4().hex[:8]}"
    # No compliance_tags on the skill -> Gate 1 passes; the finance fallback in
    # Gate 5b is what injects SOX on the write.
    skill = {"skill_id": "gl_post_entry", "department": "finance",
             "confidence": 0.9,
             "actuation": {"system": "netsuite", "object_type": "journal_entry",
                           "external_id": "je-778", "operation": "UPDATE",
                           "payload": {"amount": 250000}}}
    # is_financial + a single (non-attributable) approver -> SOX four-eyes
    # unverifiable -> BLOCK.
    context = {"tenant_id": t, "execution_id": exec_id,
               "is_financial": True, "has_human_approver": False}

    async def run():
        # The executor committed SUCCESS_CLEAN before Gate 5b; seed that row so
        # _mark_execution_failed has something to rewrite (exec_engine is stubbed).
        async with AsyncSessionLocal() as db:
            db.add(SkillExecution(id=exec_id, tenant_id=t,
                                  skill_id_name="gl_post_entry",
                                  status="SUCCESS_CLEAN", agent_state="EXECUTING"))
            await db.commit()

        executor = AgentExecutor(ComplianceEngine(), None)
        result = await executor.execute_skill(skill, context, hitl_pre_approved=True)
        assert result["status"] == "BLOCKED_ACTUATION", result
        assert result.get("skill_output_produced") is True

        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(SkillExecution).where(
                SkillExecution.id == exec_id))).scalar_one()
            assert row.status == "BLOCKED_ACTUATION", row.status
            assert row.agent_state == "FAILED", row.agent_state

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
