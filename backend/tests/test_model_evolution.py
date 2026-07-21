"""AI Foundry Phase 3 — model evolution: real evaluation + gated promotion.

Uses an injected fake router (no LLM) so scoring, the win rule, the
simulated-cannot-promote guard, and the gated promotion are all deterministic.
"""
import pytest
from sqlalchemy import select

from app.services.foundry import model_evolution
from app.models.foundry import TrainingExample, LABEL_APPROVED
from app.models.settings import TenantLLMConfig

TENANT = "tenant_acme"
IDEAL = "APPROVE the request"


class FakeRouter:
    """Candidate returns the ideal answer (scores 1.0); baseline returns junk."""
    def __init__(self, candidate, simulated=False):
        self.candidate = candidate
        self.simulated = simulated

    async def complete(self, prompt, model, temperature=0.0, max_tokens=256):
        content = IDEAL if model == self.candidate else "DENY everything"
        return {"content": content, "simulated": self.simulated}


async def _seed(db, n):
    for i in range(n):
        db.add(TrainingExample(
            tenant_id=TENANT, domain="finance",
            instruction=f"Should invoice {i} be approved?",
            context={"amount": 100 + i},
            ideal_answer=IDEAL,
            evaluation_label=LABEL_APPROVED, quality_score=0.9,
            human_verified=True, source="mined", source_execution_id=f"ex{i}",
        ))
    await db.commit()


def test_score_text_metric():
    assert model_evolution.score_text("APPROVE", "APPROVE") == 1.0
    assert model_evolution.score_text("", "x") == 0.0
    assert 0.0 < model_evolution.score_text("approve invoice", IDEAL) < 1.0


@pytest.mark.asyncio
async def test_winning_candidate_reaches_review_then_promotes(db):
    await _seed(db, 6)
    cand = "ollama/qwen2.5-coder:7b-ft"

    run = await model_evolution.run_evaluation(
        db, TENANT, tier="classification", candidate_model=cand,
        baseline_model="ollama/baseline", router=FakeRouter(cand),
    )
    assert run.simulated is False
    assert run.eval_size == 6
    assert run.candidate_score == 1.0
    assert run.baseline_score < run.candidate_score
    assert run.win is True
    assert run.status == "PENDING_REVIEW", "a win must await human approval, never auto-apply"

    promoted = await model_evolution.promote(db, TENANT, run.id, approver="admin@acme")
    assert promoted.status == "PROMOTED"
    assert promoted.decided_by == "admin@acme"

    # The tenant's BYOK routing for the tier now points at the candidate.
    cfg = (await db.execute(
        select(TenantLLMConfig).where(
            TenantLLMConfig.tenant_id == TENANT,
            TenantLLMConfig.layer == "TIER_2_STANDARD",
        )
    )).scalar_one()
    assert cfg.model_name == cand
    assert cfg.capability_profile == {}, "promotion must force a re-probe"


@pytest.mark.asyncio
async def test_simulated_eval_cannot_win_or_promote(db):
    await _seed(db, 6)
    cand = "gpt-4o"
    run = await model_evolution.run_evaluation(
        db, TENANT, tier="reasoning", candidate_model=cand,
        router=FakeRouter(cand, simulated=True),
    )
    assert run.simulated is True
    assert run.win is False
    assert run.status == "EVALUATED"
    with pytest.raises(ValueError, match="simulated"):
        await model_evolution.promote(db, TENANT, run.id, approver="admin")


@pytest.mark.asyncio
async def test_insufficient_examples_fails_gracefully(db):
    await _seed(db, 2)   # below MIN_EVAL_EXAMPLES
    run = await model_evolution.run_evaluation(
        db, TENANT, tier="fast", candidate_model="x",
        router=FakeRouter("x"),
    )
    assert run.status == "FAILED"
    assert "insufficient" in (run.error or "")


@pytest.mark.asyncio
async def test_non_winning_run_cannot_be_promoted(db):
    await _seed(db, 6)
    # Candidate == baseline behavior → no win (both return junk vs IDEAL).
    run = await model_evolution.run_evaluation(
        db, TENANT, tier="fast", candidate_model="model-a",
        baseline_model="model-b", router=FakeRouter("nobody"),
    )
    assert run.win is False
    with pytest.raises(ValueError):
        await model_evolution.promote(db, TENANT, run.id, approver="admin")
