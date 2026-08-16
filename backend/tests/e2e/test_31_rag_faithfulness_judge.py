"""
KAEOS E2E Test 31 — RAG Faithfulness LLM Judge

Runs llm_judge_faithful against the real local Ollama model: a grounded answer
must be judged faithful, an invented answer unfaithful. Direct service call
(no backend needed) - the judge is a library function gated to this lane via
the ollama marker; the unit lane covers parsing with a stubbed router.
"""
import pytest

from app.services.rag_eval import llm_judge_faithful


@pytest.mark.asyncio
@pytest.mark.ollama
class TestRagFaithfulnessJudge:

    async def test_grounded_answer_judged_faithful(self, has_ollama):
        if not has_ollama:
            pytest.skip("LLM judge needs a reachable local model")
        out = await llm_judge_faithful(
            "Full-time employees accrue 20 vacation days per year.",
            ["Full-time employees accrue 20 vacation days per year.",
             "The company matches 401k contributions up to 4 percent."],
        )
        assert out["faithful"] is not None, f"judge returned no verdict: {out}"
        assert out["faithful"] is True, f"grounded answer judged unfaithful: {out}"

    async def test_invented_answer_judged_unfaithful(self, has_ollama):
        if not has_ollama:
            pytest.skip("LLM judge needs a reachable local model")
        out = await llm_judge_faithful(
            "Employees receive unlimited vacation and a free company car.",
            ["Full-time employees accrue 20 vacation days per year."],
        )
        assert out["faithful"] is not None, f"judge returned no verdict: {out}"
        assert out["faithful"] is False, f"invented answer judged faithful: {out}"
