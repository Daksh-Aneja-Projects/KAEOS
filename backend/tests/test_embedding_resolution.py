"""Dev-path semantic search: the zero-key SQLite stack routes embeddings to a
local Ollama model instead of non-semantic pseudo-vectors.

The resolver decision is tested deterministically (monkeypatched reachability).
An end-to-end real-embedding check runs against a live Ollama when one is present
and SKIPS otherwise, so CI without Ollama stays green while local dev proves the
embeddings are genuinely semantic.
"""
import pytest

from app.services import llm_router as lr
from app.services.llm_router import LLMRouter


@pytest.mark.asyncio
async def test_cloud_key_present_keeps_cloud_model(monkeypatch):
    router = LLMRouter(api_keys={"openai": "sk-test"})
    model, api_base = await router._resolve_embedding_model("text-embedding-3-small")
    assert model == "text-embedding-3-small"
    assert api_base is None


@pytest.mark.asyncio
async def test_no_key_sqlite_ollama_reachable_routes_local(monkeypatch):
    async def _reachable(_base):
        return True
    monkeypatch.setattr(lr, "_ollama_reachable", _reachable)

    router = LLMRouter()  # no keys
    model, api_base = await router._resolve_embedding_model("text-embedding-3-small")
    assert model.startswith("ollama/"), f"expected local ollama routing, got {model}"
    assert api_base  # a base url was supplied


@pytest.mark.asyncio
async def test_no_key_ollama_unreachable_falls_back(monkeypatch):
    async def _unreachable(_base):
        return False
    monkeypatch.setattr(lr, "_ollama_reachable", _unreachable)

    router = LLMRouter()
    model, api_base = await router._resolve_embedding_model("text-embedding-3-small")
    assert model == "text-embedding-3-small"  # unchanged; embed() will pseudo-fall-back
    assert api_base is None


@pytest.mark.asyncio
async def test_ollama_model_requested_gets_base_url(monkeypatch):
    router = LLMRouter()
    model, api_base = await router._resolve_embedding_model("ollama/nomic-embed-text:latest")
    assert model == "ollama/nomic-embed-text:latest"
    assert api_base


@pytest.mark.ollama
@pytest.mark.asyncio
async def test_real_local_embeddings_are_semantic():
    """When a live Ollama with an embedding model is present, embeddings are REAL
    and semantic: a related pair is more similar than an unrelated pair. Skips when
    no local embedding model is available (CI)."""
    from app.core.polystore.vector_store import _cosine

    router = LLMRouter()
    vecs = await router.embed([
        "The quarterly revenue increased sharply.",
        "Sales grew a lot this quarter.",
        "The office cafeteria serves lunch at noon.",
    ])
    if router.embeddings_simulated:
        pytest.skip("no live Ollama embedding model — real-embedding check skipped")

    related = _cosine(vecs[0], vecs[1])
    unrelated = _cosine(vecs[0], vecs[2])
    assert related > unrelated, f"real embeddings should be semantic: {related} !> {unrelated}"
    assert len(vecs[0]) == 768, "nomic-embed-text is 768-dim"
