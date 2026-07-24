"""v4 IP-6 — Causal Discovery.

Lagged cross-correlation over daily adverse-event series. Deterministic. Verifies
the correlation helper, the honest insufficient path, and that a planted lead-lag
pattern (dept A's failures precede dept B's by a day) surfaces as A -> B.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.domain import Skill, SkillExecution
from app.services import causal

pytestmark = pytest.mark.asyncio


def test_pearson_perfect_positive():
    assert causal._pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_flat_is_none():
    assert causal._pearson([1, 1, 1, 1], [2, 4, 6, 8]) is None


def test_is_adverse():
    assert causal._is_adverse("FAILED_RULE_MISMATCH")
    assert causal._is_adverse("HUMAN_OVERRIDDEN")
    assert not causal._is_adverse("SUCCESS_CLEAN")


async def test_insufficient_history(db):
    res = await causal.discover(db, "tenant_empty_causal", days=45)
    assert res["insufficient"] is True
    assert res["links"] == []


async def test_planted_lead_lag_surfaces_link(db):
    t = "tenant_causal1"
    # Two departments, each with one skill.
    db.add(Skill(id=str(uuid.uuid4()), skill_id="eng_deploy", tenant_id=t,
                 department="engineering", domain="engineering", status="ACTIVE", confidence=0.9))
    db.add(Skill(id=str(uuid.uuid4()), skill_id="support_sla", tenant_id=t,
                 department="support", domain="support", status="ACTIVE", confidence=0.9))
    await db.commit()

    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    # engineering adverse on days 0,1,2,3,4,5,6 with a rising pattern; support adverse
    # one day LATER mirroring engineering (A[t] ~ B[t+1]).
    eng_pattern = [3, 0, 3, 0, 3, 0, 3, 0]
    for i, n in enumerate(eng_pattern):
        for _ in range(n):
            db.add(SkillExecution(id=str(uuid.uuid4()), skill_id_name="eng_deploy", tenant_id=t,
                                  status="FAILED_RULE_MISMATCH", started_at=base + timedelta(days=i)))
        # support fails the NEXT day with the same count.
        for _ in range(n):
            db.add(SkillExecution(id=str(uuid.uuid4()), skill_id_name="support_sla", tenant_id=t,
                                  status="HUMAN_OVERRIDDEN", started_at=base + timedelta(days=i + 1)))
    await db.commit()

    res = await causal.discover(db, t, days=60, min_strength=0.4)
    assert res["insufficient"] is False
    # engineering -> support should appear as a 'leads' link.
    eng_to_support = [l for l in res["links"] if l["source"] == "engineering" and l["target"] == "support"]
    assert eng_to_support, f"expected engineering->support link, got {res['links']}"
    assert eng_to_support[0]["lag_days"] == 1
    assert eng_to_support[0]["strength"] >= 0.4
