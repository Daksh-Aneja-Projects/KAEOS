"""Perf — embedding cache.

An embedding is a pure function of (model, text), so caching returns a
byte-identical vector while eliminating the repeat provider call. Verifies the
cache helpers, and that a repeated embed serves from cache (0 extra provider hits)
while a novel text still calls the provider — with identical output either way.
"""
import pytest

from app.services import llm_router as R
# The embedding-cache primitives live in llm_support (the router re-exports the
# helpers); patch the cache state where it actually lives.
from app.services import llm_support as S


def test_cache_key_is_deterministic_and_model_scoped():
    a = S._embed_key("m1", "hello")
    assert a == S._embed_key("m1", "hello")
    assert a != S._embed_key("m2", "hello")
    assert a != S._embed_key("m1", "world")


def test_lru_eviction(monkeypatch):
    monkeypatch.setattr(S, "_EMBED_CACHE", S._OrderedDict())
    monkeypatch.setattr(S, "_EMBED_CACHE_MAX", 3)
    for i in range(5):
        S._embed_cache_put(f"k{i}", [float(i)])
    # Only the last 3 survive.
    assert S._embed_cache_get("k0") is None
    assert S._embed_cache_get("k4") == [4.0]
    assert len(S._EMBED_CACHE) == 3


@pytest.mark.asyncio
async def test_embed_serves_cache_and_skips_provider(monkeypatch):
    monkeypatch.setattr(S, "_EMBED_CACHE", S._OrderedDict())
    router = R.LLMRouter()

    calls = {"n": 0}

    class _Item(dict):
        pass

    async def fake_aembedding(model, input, **kw):
        calls["n"] += 1
        class Resp:
            data = [{"embedding": [float(len(t)), 0.5]} for t in input]
            usage = None
        return Resp()

    # Force "provider available" and stub litellm.aembedding.
    async def _avail(*a, **k):
        return True
    monkeypatch.setattr(router, "provider_available", _avail)
    import litellm
    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    v1 = await router.embed(["alpha", "beta"], model="ollama/nomic-embed-text:latest")
    assert calls["n"] == 1                     # one provider call for two misses
    v2 = await router.embed(["alpha", "beta"], model="ollama/nomic-embed-text:latest")
    assert calls["n"] == 1                     # fully cached -> NO extra provider call
    assert v2 == v1                            # byte-identical output

    # A novel text embeds only the miss; the cached one is reused.
    v3 = await router.embed(["alpha", "gamma"], model="ollama/nomic-embed-text:latest")
    assert calls["n"] == 2
    assert v3[0] == v1[0]                       # 'alpha' from cache, identical
