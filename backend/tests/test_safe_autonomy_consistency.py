"""Regression: the north-star metric must have exactly ONE definition.

/billing/roi used to compute its own safe-autonomy rate from `hitl_required ==
False` alone. That counts an execution that ran without a human and then FAILED
as "safe autonomy", so the dashboard headline read materially higher than
/metrics/safe-autonomy and the Time Machine, which both require
`hitl_required == False AND status == SUCCESS_CLEAN`.

A north-star metric with two definitions is worse than no metric, and the
divergent one was the flattering one. /billing/roi now delegates to the single
canonical implementation; the looser measure survives only under an honest name
(`unattended_rate_pct`).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain import Skill, SkillExecution
from app.services.safe_autonomy import compute_safe_autonomy

TENANT = "tenant_sar_consistency"


async def _seed(db):
    """3 executions: one safe-autonomous, one unattended-but-FAILED, one routed
    to a human. Honest rate = 1/3. The old loose rate would have been 2/3."""
    skill = Skill(id=str(uuid.uuid4()), skill_id=f"sar_{uuid.uuid4().hex[:6]}",
                  tenant_id=TENANT, department="support", domain="support",
                  status="ACTIVE", confidence=0.9)
    db.add(skill)
    await db.flush()
    now = datetime.now(timezone.utc) - timedelta(days=1)
    rows = [
        # ran without a human AND completed cleanly -> the only safe-autonomous one
        ("SUCCESS_CLEAN", False),
        # ran without a human and FAILED -> must NOT count as safe autonomy
        ("FAILED_RULE_MISMATCH", False),
        # routed to a human -> not autonomous
        ("SUCCESS_CLEAN", True),
    ]
    for status, hitl in rows:
        db.add(SkillExecution(
            id=str(uuid.uuid4()), skill_db_id=skill.id, skill_id_name=skill.skill_id,
            tenant_id=TENANT, status=status, route_type="SKILL_EXEC",
            started_at=now, duration_ms=100, hitl_required=hitl, outcome_type=status,
        ))
    await db.commit()


async def test_canonical_excludes_unattended_failures(db):
    await _seed(db)
    sar = await compute_safe_autonomy(db, TENANT, days=3650)
    assert sar["total_executions"] == 3
    assert sar["safe_autonomous"] == 1, \
        "an unattended FAILURE must not count toward safe autonomy"
    assert sar["safe_autonomy_rate"] == pytest.approx(1 / 3, abs=1e-4)


async def test_roi_matches_canonical_and_labels_the_loose_measure(db, async_client, monkeypatch):
    """/billing/roi must report the canonical rate, not its own looser one."""
    await _seed(db)

    # The route resolves the tenant from the request; point it at our fixture data.
    from app.core import tenant as tenant_mod
    monkeypatch.setattr(tenant_mod, "_DEV_TENANT",
                        {"tenant_id": TENANT, "role": "admin", "name": "dev_user"})

    r = await async_client.get("/api/v1/billing/roi")
    assert r.status_code == 200, r.text
    body = r.json()

    sar = await compute_safe_autonomy(db, TENANT, days=3650)
    expected_pct = round(sar["safe_autonomy_rate"] * 100, 1)

    assert body["safe_autonomy_rate_pct"] == expected_pct, \
        "/billing/roi diverged from the canonical safe-autonomy definition"
    assert body["safe_autonomy_rate_pct"] == pytest.approx(33.3, abs=0.1)

    # The loose measure may still be reported, but never as the north star.
    assert body["unattended_rate_pct"] == pytest.approx(66.7, abs=0.1)
    assert body["unattended_rate_pct"] != body["safe_autonomy_rate_pct"]

    # Honesty guarantees that must not regress.
    assert body["total_hours_saved"] is None
    assert body["total_cost_reduction"] is None
    assert body["safe_autonomy_window_days"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
