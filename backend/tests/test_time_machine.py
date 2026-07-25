"""v4 IP-3 — Enterprise Time Machine.

Timeline classification, state-as-of reconstruction, and counterfactual recompute
of the north-star with one decision flipped — all over real execution rows.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.domain import SkillExecution
from app.services import time_machine



async def _seed(db, tenant, *, when, status, hitl, sid="s1"):
    db.add(SkillExecution(id=str(uuid.uuid4()), skill_id_name=sid, tenant_id=tenant,
                          status=status, hitl_required=hitl, started_at=when))
    await db.commit()


async def test_timeline_classifies_and_rate(db):
    t = "tenant_tm1"
    base = datetime.now(timezone.utc) - timedelta(days=1)
    await _seed(db, t, when=base, status="SUCCESS_CLEAN", hitl=False)   # safe
    await _seed(db, t, when=base, status="SUCCESS_CLEAN", hitl=True)    # routed_to_human
    await _seed(db, t, when=base, status="FAILED_RULE_MISMATCH", hitl=False)  # failed
    tl = await time_machine.timeline(db, t)
    assert tl["total"] == 3
    assert tl["current_rate"] == pytest.approx(1 / 3, abs=1e-3)  # rounded to 4dp
    klasses = {e["klass"] for e in tl["events"]}
    assert {"safe_autonomous", "routed_to_human", "failed"} <= klasses


async def test_state_as_of_reconstructs_history(db):
    t = "tenant_tm2"
    now = datetime.now(timezone.utc)
    await _seed(db, t, when=now - timedelta(days=3), status="SUCCESS_CLEAN", hitl=False)
    await _seed(db, t, when=now - timedelta(days=1), status="FAILED_X", hitl=False)
    # As of 2 days ago: only the first (safe) decision exists -> rate 1.0
    s = await time_machine.state_as_of(db, t, at=(now - timedelta(days=2)).isoformat())
    assert s["decisions_so_far"] == 1
    assert s["safe_autonomy_rate"] == 1.0


async def test_counterfactual_approve_raises_rate(db):
    t = "tenant_tm3"
    now = datetime.now(timezone.utc)
    await _seed(db, t, when=now, status="SUCCESS_CLEAN", hitl=False)          # safe
    exec_id = str(uuid.uuid4())
    db.add(SkillExecution(id=exec_id, skill_id_name="s2", tenant_id=t,
                          status="HUMAN_OVERRIDDEN", hitl_required=True, started_at=now))  # fallout
    await db.commit()

    cf = await time_machine.counterfactual(db, t, execution_id=exec_id, flip="approve")
    assert cf["before_rate"] == pytest.approx(0.5)   # 1 of 2 safe
    assert cf["after_rate"] == pytest.approx(1.0)    # flipping the override to safe -> 2 of 2
    assert cf["delta"] == pytest.approx(0.5)


async def test_counterfactual_fail_lowers_rate(db):
    t = "tenant_tm4"
    now = datetime.now(timezone.utc)
    exec_id = str(uuid.uuid4())
    db.add(SkillExecution(id=exec_id, skill_id_name="s1", tenant_id=t,
                          status="SUCCESS_CLEAN", hitl_required=False, started_at=now))  # safe
    await db.commit()
    await _seed(db, t, when=now, status="SUCCESS_CLEAN", hitl=False)  # another safe

    cf = await time_machine.counterfactual(db, t, execution_id=exec_id, flip="fail")
    assert cf["before_rate"] == 1.0
    assert cf["after_rate"] == pytest.approx(0.5)


async def test_counterfactual_missing_execution(db):
    t = "tenant_tm5"
    await _seed(db, t, when=datetime.now(timezone.utc), status="SUCCESS_CLEAN", hitl=False)
    cf = await time_machine.counterfactual(db, t, execution_id="ghost", flip="approve")
    assert cf.get("error")
