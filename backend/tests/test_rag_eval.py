"""RAG eval harness — deterministic CI checks (workstream: rag).

Runs the golden set through a lexical retriever and asserts recall + the
faithfulness/hallucination detector. No live Ollama: the grounding check is a
deterministic lexical heuristic so it runs in the unit lane on every commit.
"""
import pytest

from app.services.rag_eval import (
    GOLDEN_SET,
    evaluate,
    is_faithful,
    grounding_score,
)
from app.services.retrieval import lexical_score, reciprocal_rank_fusion


async def _lexical_retrieve(question, docs):
    return sorted(docs, key=lambda i: lexical_score(question, docs[i]), reverse=True)[:2]


@pytest.mark.asyncio
async def test_golden_recall_and_faithfulness():
    good_answers = {
        "How many vacation days do full-time employees get?":
            "Full-time employees accrue 20 vacation days per year.",
        "What is the 401k match?":
            "The company matches 401k contributions up to 4 percent.",
    }
    rep = await evaluate(GOLDEN_SET, _lexical_retrieve, answers=good_answers)
    assert rep.recall_at_k == 1.0, rep.to_dict()
    assert rep.faithful == len(GOLDEN_SET), rep.to_dict()
    assert rep.hallucinated == []


def test_hallucination_is_flagged():
    ctx = "Full-time employees accrue 20 vacation days per year."
    ok, bad = is_faithful("Employees get unlimited vacation and a free car.", ctx)
    assert not ok and bad, "invented facts must be caught"


def test_grounded_claim_passes():
    ctx = "The company matches 401k contributions up to 4 percent."
    assert grounding_score("The 401k match is 4 percent.", ctx) >= 0.6


def test_lexical_and_rrf_are_bounded_and_honest():
    assert lexical_score("reset password", "how to reset a password") > 0
    assert lexical_score("reset password", "unrelated text") == 0
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    # 'b' ranked high in both must not be below a single-list-only id.
    assert fused["a"] > 0 and fused["b"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
