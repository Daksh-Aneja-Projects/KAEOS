"""v4 IP-4 — Autonomy Wargaming.

Adversarial cascade resilience scoring grounded in the real twin. Verifies
compounding damage, grade thresholds, safe-response classification, weakest link,
and the unknown-playbook path.
"""
import uuid

import pytest

from app.models.domain import Skill, SkillExecution
from app.services import wargame



async def _seed_dept(db, tenant, dept, *, conf, n_adverse=0, n_ok=0):
    sid = f"{dept}_s_{uuid.uuid4().hex[:5]}"
    db.add(Skill(id=str(uuid.uuid4()), skill_id=sid, tenant_id=tenant, department=dept,
                 domain=dept, status="ACTIVE", confidence=conf))
    for _ in range(n_adverse):
        db.add(SkillExecution(id=str(uuid.uuid4()), skill_id_name=sid, tenant_id=tenant,
                              status="FAILED_RULE_MISMATCH"))
    for _ in range(n_ok):
        db.add(SkillExecution(id=str(uuid.uuid4()), skill_id_name=sid, tenant_id=tenant,
                              status="SUCCESS_CLEAN"))
    await db.commit()


async def test_cascade_degrades_integrity_and_grades(db):
    t = "tenant_wg1"
    await _seed_dept(db, t, "engineering", conf=0.9, n_ok=10)
    await _seed_dept(db, t, "legal", conf=0.9, n_ok=10)
    await _seed_dept(db, t, "support", conf=0.9, n_ok=10)

    res = await wargame.run_wargame(db, t, playbook="cyber_cascade")
    assert len(res["steps"]) == 3
    # Integrity monotonically decreases across the cascade.
    integ = [s["integrity_after"] for s in res["steps"]]
    assert integ == sorted(integ, reverse=True)
    assert res["resilience_score"] == res["steps"][-1]["integrity_after"]
    assert res["grade"] in ("A", "B", "C", "D", "F")
    assert res["weakest_link"]["department"] is not None


async def test_fragile_org_scores_worse_than_robust(db):
    tr, tf = "tenant_wg_robust", "tenant_wg_fragile"
    for dept in ("engineering", "legal", "support"):
        await _seed_dept(db, tr, dept, conf=0.98, n_ok=20)                 # robust
        await _seed_dept(db, tf, dept, conf=0.5, n_adverse=15, n_ok=1)     # fragile
    robust = await wargame.run_wargame(db, tr, playbook="cyber_cascade")
    fragile = await wargame.run_wargame(db, tf, playbook="cyber_cascade")
    assert robust["resilience_score"] > fragile["resilience_score"]


async def test_safe_response_flags_high_severity_as_human(db):
    t = "tenant_wg2"
    await _seed_dept(db, t, "engineering", conf=0.9, n_ok=5)
    await _seed_dept(db, t, "legal", conf=0.9, n_ok=5)
    await _seed_dept(db, t, "support", conf=0.9, n_ok=5)
    res = await wargame.run_wargame(db, t, playbook="cyber_cascade")
    # cyber_cascade: severities 95, 80, 60 -> two need a human, one autonomous.
    responses = [s["response"] for s in res["steps"]]
    assert responses[0] == "human_in_loop"   # severity 95
    assert responses[2] == "autonomous"      # severity 60
    assert res["safe_response_rate"] == pytest.approx(1 / 3, abs=1e-3)


async def test_unknown_playbook_errors(db):
    res = await wargame.run_wargame(db, "t", playbook="does_not_exist")
    assert res.get("error")


async def test_custom_cascade(db):
    t = "tenant_wg3"
    await _seed_dept(db, t, "finance", conf=0.8, n_ok=5)
    res = await wargame.run_wargame(db, t, custom=[("BUDGET_CUT", "finance", 90)])
    assert res["playbook"] == "custom"
    assert len(res["steps"]) == 1
    assert res["steps"][0]["response"] == "human_in_loop"  # severity 90
