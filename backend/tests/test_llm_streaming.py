"""The streaming path must be exactly as governed as the blocking one.

`stream_complete` mirrors `complete`'s orchestration (budget gate, tier
resolution, data residency, cost metering) rather than calling past it, and both
share `_prepare_call` so the PII scrub and residency rules cannot diverge. These
tests pin that, with the provider replaced by a stub so no model is called.
"""
import sys
import types

import pytest

from app.services.llm_router import LLMRouter


class _Delta:
    def __init__(self, content): self.content = content


class _Choice:
    def __init__(self, content): self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content=None, usage=None):
        self.choices = [_Choice(content)]
        self.usage = usage


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7
    total_tokens = 18


def _install_fake_litellm(monkeypatch, chunks, capture: dict):
    """Replace litellm with a stub that records what it was called with."""
    mod = types.ModuleType("litellm")

    async def acompletion(**kwargs):
        capture.update(kwargs)
        if kwargs.get("stream"):
            async def gen():
                for c in chunks:
                    yield c
            return gen()
        raise AssertionError("streaming test must not take the blocking path")

    mod.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", mod)
    return mod


@pytest.fixture
def router(monkeypatch):
    r = LLMRouter()
    monkeypatch.setattr(LLMRouter, "provider_available", lambda self, keys=None: _true())
    return r


async def _true():
    return True


@pytest.mark.asyncio
async def test_stream_complete_yields_deltas_in_order(router, monkeypatch):
    cap: dict = {}
    _install_fake_litellm(monkeypatch, [_Chunk("Hel"), _Chunk("lo "), _Chunk("world")], cap)

    out = []
    async for d in router.stream_complete(prompt="hi", model_tier="fast"):
        out.append(d)

    assert out == ["Hel", "lo ", "world"]
    assert cap["stream"] is True
    # Usage must be requested, or a streamed call escapes cost metering.
    assert cap["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_streamed_call_is_metered_like_a_blocking_one(router, monkeypatch):
    cap: dict = {}
    _install_fake_litellm(
        monkeypatch, [_Chunk("a"), _Chunk(None, usage=_Usage())], cap
    )
    recorded = {}

    async def _spy(self, model, model_tier, usage, latency_ms):
        recorded.update({"model": model, "tier": model_tier, "usage": usage})

    monkeypatch.setattr(LLMRouter, "_record_cost", _spy)

    async for _ in router.stream_complete(prompt="hi", model_tier="fast"):
        pass

    assert recorded["usage"]["prompt_tokens"] == 11
    assert recorded["usage"]["completion_tokens"] == 7
    assert recorded["tier"] == "fast"


@pytest.mark.asyncio
async def test_budget_gate_runs_before_any_token_is_streamed(router, monkeypatch):
    """A blocked tenant must not reach the model on the streaming path either."""
    _install_fake_litellm(monkeypatch, [_Chunk("should not be reached")], {})

    async def _blocked(self, prompt):
        raise PermissionError("budget exhausted")

    monkeypatch.setattr(LLMRouter, "_check_budget_gate", _blocked)

    with pytest.raises(PermissionError):
        async for _ in router.stream_complete(prompt="hi", model_tier="fast"):
            pass


@pytest.mark.asyncio
async def test_no_fallback_after_a_delta_has_been_emitted(router, monkeypatch):
    """Falling back mid-stream would append a second answer to a partial one."""
    mod = types.ModuleType("litellm")
    attempts = {"n": 0}

    async def acompletion(**kwargs):
        attempts["n"] += 1

        async def gen():
            yield _Chunk("partial")
            raise RuntimeError("provider died mid-stream")

        return gen()

    mod.acompletion = acompletion
    monkeypatch.setitem(sys.modules, "litellm", mod)

    got = []
    with pytest.raises(RuntimeError):
        async for d in router.stream_complete(prompt="hi", model_tier="fast"):
            got.append(d)

    assert got == ["partial"]
    assert attempts["n"] == 1, "must not retry another model once text was emitted"


@pytest.mark.asyncio
async def test_prepare_call_is_shared_and_sets_local_api_base(router):
    messages, model, api_base, _key, is_local = await router._prepare_call(
        "ollama/qwen2.5-coder:7b", "the prompt", "the system prompt", None
    )
    assert is_local is True
    assert api_base and api_base.startswith("http")
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "the prompt"}


@pytest.mark.asyncio
async def test_unknown_tier_is_rejected_on_the_streaming_path_too(router):
    with pytest.raises(ValueError):
        async for _ in router.stream_complete(prompt="hi", model_tier="not-a-tier"):
            pass
