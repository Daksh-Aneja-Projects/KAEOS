"""M9: a federated swarm hint cannot relax our governance on its own.

import_swarm_weight_to_tenant boosted a matching local skill's confidence by
+0.15 UNCONDITIONALLY on a foreign hash match (only the VALIDATED_PEER tier was
evidence-gated). Both a confidence boost and the tier move a skill toward the
autonomy threshold and away from HITL, so neither is applied now unless THIS
tenant's own measured history backs it."""
import json
import uuid

import pytest
from sqlalchemy import select

from app.models.domain import ProvenanceLedger, Skill, SkillExecution
from app.services.federated_engine import FederatedEngine

TENANT = "tenant_m9"


@pytest.mark.asyncio
async def test_swarm_boost_requires_local_evidence(db):
    steps = [{"action": "assess_risk", "tool": "none"}]
    unproven = Skill(id=str(uuid.uuid4()), skill_id="ops.unproven", tenant_id=TENANT,
                     department="operations", domain="operations", status="ACTIVE",
                     confidence=0.5, confidence_tier="UNVALIDATED", steps=steps)
    proven = Skill(id=str(uuid.uuid4()), skill_id="ops.proven", tenant_id=TENANT,
                   department="operations", domain="operations", status="ACTIVE",
                   confidence=0.5, confidence_tier="UNVALIDATED", steps=steps)
    db.add_all([unproven, proven])
    for _ in range(3):
        db.add(SkillExecution(id=str(uuid.uuid4()), tenant_id=TENANT,
                              skill_id_name="ops.proven", status="SUCCESS_CLEAN",
                              hitl_required=False))

    phash = FederatedEngine._extract_zero_knowledge_procedural_weight(unproven)
    payload = {"abstract_domain": "operations", "procedural_hash": phash, "global_id": "g1"}
    db.add(ProvenanceLedger(id=str(uuid.uuid4()), tenant_id=TENANT,
                            event_type="FEDERATED_SWARM_EXPORT", chain_hash="receipt-1",
                            reasoning=f"swarm export | PAYLOAD: {json.dumps(payload)}"))
    await db.commit()

    boosted = await FederatedEngine.import_swarm_weight_to_tenant(db, TENANT, "receipt-1")
    assert boosted == 1, "only the locally-proven skill is boosted"

    u = (await db.execute(select(Skill).where(
        Skill.skill_id == "ops.unproven", Skill.tenant_id == TENANT))).scalar_one()
    p = (await db.execute(select(Skill).where(
        Skill.skill_id == "ops.proven", Skill.tenant_id == TENANT))).scalar_one()

    assert u.confidence == 0.5 and u.confidence_tier == "UNVALIDATED", \
        "a foreign hint with no local evidence must change nothing"
    assert abs(p.confidence - 0.65) < 1e-6 and p.confidence_tier == "VALIDATED_PEER"
