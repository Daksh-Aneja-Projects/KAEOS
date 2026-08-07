"""The rule miner's prompt is the thing that costs time, so pin its shape.

Both behaviours here were real defects: the payload key the caller sends was not
the key the miner read, so every signal reached the prompt as a Python dict
repr; and the whole cluster went into the prompt, so one busy domain dominated
the request.
"""
import pytest

from app.services.extraction import RuleMiner


def _cluster(n: int, key: str = "clean_payload") -> list[dict]:
    return [{"id": f"sig_{i}", key: {"text": f"event {i}"}} for i in range(n)]


def test_signal_text_reads_either_payload_key_and_never_leaks_the_id():
    for key in ("clean_payload", "payload"):
        text = RuleMiner._signal_text({"id": "sig_1", key: {"text": "invoice approved"}})
        assert "invoice approved" in text
        # The id and the Python dict repr must not reach the prompt.
        assert "sig_1" not in text
        assert "'" not in text


def test_signal_text_passes_a_plain_string_through():
    assert RuleMiner._signal_text({"clean_payload": "raw text"}) == "raw text"


def test_signal_text_is_empty_when_there_is_no_payload():
    assert RuleMiner._signal_text({"id": "sig_1"}) == ""


@pytest.mark.asyncio
async def test_prompt_is_capped_and_reports_the_full_cluster_size(monkeypatch):
    """Only MAX_PROMPT_SIGNALS reach the model, but the evidence count is true."""
    seen = {}

    class _FakeRouter:
        async def complete(self, prompt: str, model_tier: str, max_tokens: int = 2048):
            seen["prompt"] = prompt
            seen["max_tokens"] = max_tokens
            return '{"statement": "s", "trigger_json": {}, "action_json": {}}'

    import app.services.llm_router as llm_router
    monkeypatch.setattr(llm_router, "LLMRouter", _FakeRouter)

    miner = RuleMiner()
    total = miner.MAX_PROMPT_SIGNALS + 40
    out = await miner.extract_rule(_cluster(total))

    lines = [ln for ln in seen["prompt"].splitlines() if ln.startswith("- ")]
    assert len(lines) == miner.MAX_PROMPT_SIGNALS, "prompt must be capped"
    # Confidence is evidence, not sample size: it reports every instance.
    assert out["confidence_basis"] == f"{total} consistent instances"
    assert seen["max_tokens"] == 256


@pytest.mark.asyncio
async def test_below_minimum_cluster_returns_none():
    assert await RuleMiner().extract_rule(_cluster(2)) is None
