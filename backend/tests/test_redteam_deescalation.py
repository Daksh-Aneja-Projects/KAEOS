"""M1: a failing red-team scan actually costs the skill its autonomy.

Scans were recorded and then ignored — a skill proven vulnerable kept running
unattended. A FAILED scan now drops the skill below the autonomy floor and tags
it SPECULATIVE (Gate 3 routes it to a human), recording why on its guardrails.
(ChaosInjector, dead + cross-tenant-unsafe, was deleted in the same change.)"""
import pytest
from sqlalchemy import select

from app.api.routes.redteam import run_skill_scan
from app.models.domain import Skill

TENANT = "tenant_m1"


@pytest.mark.asyncio
async def test_failed_scan_deescalates_the_skill(db):
    # A guardrail with a min but no max is a CRITICAL boundary vuln -> FAILED,
    # deterministically (no LLM needed for the boundary scan).
    db.add(Skill(id="sk-m1", skill_id="ops.vuln", tenant_id=TENANT,
                 department="operations", domain="operations", status="ACTIVE",
                 confidence=0.95, confidence_tier="VALIDATED_DH",
                 guardrails={"amount": {"min": 0}}, steps=[]))
    await db.commit()

    res = await run_skill_scan("ops.vuln", {"tenant_id": TENANT, "role": "operator"}, db)
    assert res["autonomy_deescalated"] is True

    skill = (await db.execute(select(Skill).where(
        Skill.skill_id == "ops.vuln", Skill.tenant_id == TENANT))).scalar_one()
    assert skill.confidence <= 0.5, "a vulnerable skill drops below the autonomy floor"
    assert skill.confidence_tier == "SPECULATIVE"
    assert "redteam_deescalation" in (skill.guardrails or {})


@pytest.mark.asyncio
async def test_chaos_injector_is_gone():
    import app.services.redteam as rt
    assert not hasattr(rt, "ChaosInjector"), "dead cross-tenant-unsafe class removed"
