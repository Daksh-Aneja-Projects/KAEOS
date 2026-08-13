"""Statistical fairness (review theme E): the four-fifths rule with a
significance check replaces LLM opinion whenever cohort outcome data exists.
"""
import asyncio
import uuid

import pytest

from app.services.disparate_impact import four_fifths_test


def _cohort(sel_a, tot_a, sel_b, tot_b, attr="gender", a="female", b="male"):
    return {attr: {a: {"selected": sel_a, "total": tot_a},
                   b: {"selected": sel_b, "total": tot_b}}}


def test_clear_adverse_impact_is_flagged():
    # 10% vs 60% selection with large n: ratio 0.167, strongly significant.
    out = four_fifths_test(_cohort(10, 100, 60, 100))
    assert out["passed"] is False
    assert out["flagged"] == ["gender"]
    g = out["attributes"]["gender"]["groups"]["female"]
    assert g["below_four_fifths"] and g["statistically_significant"]


def test_parity_passes():
    out = four_fifths_test(_cohort(50, 100, 52, 100))
    assert out["passed"] is True
    assert out["flagged"] == []


def test_tiny_samples_are_advisory_not_blocking():
    # 0/2 vs 2/3 fails 4/5ths on its face but cannot be significant: the
    # verdict must be advisory, not a hard block on noise.
    out = four_fifths_test(_cohort(0, 2, 2, 3))
    assert out["passed"] is True
    assert out["attributes"]["gender"]["status"] == "ADVISORY"
    g = out["attributes"]["gender"]["groups"]["female"]
    assert g["advisory"] is True and g["small_sample"] is True


def test_single_group_reports_insufficient():
    out = four_fifths_test({"gender": {"female": {"selected": 5, "total": 10}}})
    assert out["passed"] is True
    assert out["attributes"]["gender"]["status"] == "INSUFFICIENT_GROUPS"


def test_engine_uses_statistics_and_skips_the_llm(monkeypatch):
    """With cohort data present the gate must not consult the model at all."""
    from app.services.fairness_engine import FairnessEngine
    from app.services.llm_router import LLMRouter

    async def boom(self, *a, **k):
        raise AssertionError("LLM must not be called on the statistical path")

    monkeypatch.setattr(LLMRouter, "complete", boom)

    from app.core.database import init_db
    asyncio.run(init_db())

    class _Skill:
        skill_id = "hr.hiring_screen"
        department = "hr"
        domain = "recruiting"
        steps = [{"action": "score_candidates"}]

    async def run():
        engine = FairnessEngine()
        result = await engine.score_fairness(
            _Skill(), {
                "intent": "screen candidates",
                "cohort_outcomes": {"gender": {
                    "female": {"selected": 10, "total": 100},
                    "male": {"selected": 60, "total": 100}}},
            },
            tenant_id=f"tenant_fair_{uuid.uuid4().hex[:6]}",
            execution_id=str(uuid.uuid4()),
        )
        assert result["passed"] is False
        assert result["flagged_attributes"] == ["gender"]
        assert "four-fifths" in result["rationale"]
        assert result["audit_log_id"]

    asyncio.run(run())
