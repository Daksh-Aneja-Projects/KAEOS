"""
v3 Phase 2 — the Outcome Intelligence Loop.

Recording a GOOD outcome for an autonomous execution boosts the executing skill's
confidence and shows up in the impact aggregate split by autonomous vs human.
"""
import uuid

import pytest

from app.models.domain import Skill, SkillExecution
from app.models.intelligence_metrics import OutcomeRecord

pytestmark = pytest.mark.asyncio


async def _seed_exec(db, tenant, skill_id, *, hitl_required, confidence=0.80):
    db.add(Skill(id=str(uuid.uuid4()), skill_id=skill_id, tenant_id=tenant, domain="finance",
                 confidence=confidence, status="ACTIVE"))
    ex_id = str(uuid.uuid4())
    db.add(SkillExecution(id=ex_id, skill_id_name=skill_id, tenant_id=tenant,
                          status="SUCCESS_CLEAN", hitl_required=hitl_required))
    await db.commit()
    return ex_id


async def test_good_outcome_boosts_skill_confidence(db):
    from app.api.routes.outcomes import record_outcome, OutcomeIn
    tenant = "tenant_out"
    ex_id = await _seed_exec(db, tenant, "refund_small", hitl_required=False, confidence=0.80)

    res = await record_outcome(ex_id, OutcomeIn(outcome="good"),
                               tenant={"tenant_id": tenant, "name": "t"}, db=db)
    assert res["outcome"] == "GOOD"
    assert res["new_confidence"] == 0.82  # 0.80 + 0.02

    from sqlalchemy import select
    skill = (await db.execute(select(Skill).where(Skill.skill_id == "refund_small"))).scalar_one()
    assert round(skill.confidence, 4) == 0.82


async def test_bad_outcome_reduces_confidence_and_impact_split(db):
    from app.api.routes.outcomes import record_outcome, outcome_impact, OutcomeIn
    tenant = "tenant_out2"
    ex_auto = await _seed_exec(db, tenant, "payout", hitl_required=False, confidence=0.80)
    ex_human = await _seed_exec(db, tenant, "hire", hitl_required=True, confidence=0.80)

    await record_outcome(ex_auto, OutcomeIn(outcome="bad"), tenant={"tenant_id": tenant, "name": "t"}, db=db)
    await record_outcome(ex_human, OutcomeIn(outcome="good"), tenant={"tenant_id": tenant, "name": "t"}, db=db)

    from sqlalchemy import select
    payout = (await db.execute(select(Skill).where(Skill.skill_id == "payout"))).scalar_one()
    assert round(payout.confidence, 4) == 0.75  # 0.80 - 0.05

    impact = await outcome_impact(days=30, tenant_id=tenant, db=db)
    assert impact["total"] == 2
    assert impact["distribution"] == {"good": 1, "bad": 1, "neutral": 0}
    assert impact["autonomous"]["total"] == 1 and impact["autonomous"]["good"] == 0
    assert impact["human"]["total"] == 1 and impact["human"]["good"] == 1


async def test_unknown_outcome_rejected(db):
    from app.api.routes.outcomes import record_outcome, OutcomeIn
    from fastapi import HTTPException
    ex_id = await _seed_exec(db, "t3", "s", hitl_required=False)
    with pytest.raises(HTTPException):
        await record_outcome(ex_id, OutcomeIn(outcome="maybe"), tenant={"tenant_id": "t3", "name": "t"}, db=db)
