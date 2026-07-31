"""W1E — tenant-aware LLM routing + simulated-embedding hygiene.

Proves two things deterministically (no live LLM, no live DB rows required):

  (a) ``get_llm_router`` / ``get_tenant_router`` return a router BOUND to the
      current tenant when a tenant context is present, and a bare default router
      when it is not (system jobs). Binding is what makes a tenant's promoted /
      fine-tuned models reachable at the call site.

  (b) Simulated (pseudo-vector) embeddings are STAMPED — ``simulated=True`` plus
      the embedding model name — both on the router's provenance and threaded
      into the metadata of vectors upserted through EnterpriseMemoryService, so a
      later pass can detect and re-embed / exclude them.
"""
import pytest

from app.core.context import current_tenant_id
from app.core.dependencies import get_llm_router
from app.services.llm_router import LLMRouter, get_tenant_router


# ── (a) tenant-aware routing ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_is_tenant_scoped_when_context_present():
    token = current_tenant_id.set("tenant_acme")
    try:
        router = await get_llm_router()
    finally:
        current_tenant_id.reset(token)
    assert getattr(router, "tenant_id", None) == "tenant_acme", (
        "with a tenant context, the dependency must return a tenant-bound router"
    )


@pytest.mark.asyncio
async def test_router_falls_back_to_bare_without_context():
    # No tenant set (contextvar default is None) → bare platform router.
    router = await get_llm_router()
    assert getattr(router, "tenant_id", None) is None, (
        "no tenant context must yield a bare router (system-job safe fallback)"
    )


@pytest.mark.asyncio
async def test_explicit_tenant_id_overrides_context():
    router = await get_tenant_router("tenant_explicit")
    assert getattr(router, "tenant_id", None) == "tenant_explicit"


# ── (b) simulated-embedding hygiene ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_simulated_embeddings_are_stamped(monkeypatch):
    router = LLMRouter()

    async def _no_provider(*_a, **_k):
        return False

    monkeypatch.setattr(router, "provider_available", _no_provider)

    # Dimension is model-dependent (the resolver may reroute to a local model),
    # so assert only that a real, correctly-shaped vector came back — the point
    # of this test is the provenance stamp, not the dimension.
    vecs = await router.embed(["hello world"], model="text-embedding-3-small")
    assert vecs and len(vecs[0]) > 0

    assert router.embeddings_simulated is True
    meta = router.embedding_metadata()
    assert meta["simulated"] is True
    assert meta["embedding_model"], "the embedding model name must be recorded"


class _FakeStore:
    """Captures upsert kwargs so we can assert the provenance stamp is threaded."""

    def __init__(self):
        self.upserts = []

    async def upsert(self, **kw):
        self.upserts.append(kw)


@pytest.mark.asyncio
async def test_memory_upsert_threads_simulated_stamp(monkeypatch):
    from app.services.memory import enterprise_memory as em

    fake = _FakeStore()
    monkeypatch.setattr(em, "get_vector_store", lambda: fake)

    async def _fake_tenant_router(tenant_id=None):
        r = LLMRouter()

        async def _no_provider(*_a, **_k):
            return False

        monkeypatch.setattr(r, "provider_available", _no_provider)
        return r

    monkeypatch.setattr(em, "get_tenant_router", _fake_tenant_router)

    await em.EnterpriseMemoryService.store_decision_memory(
        None, "tenant_acme", "some context", {"action": "approve"}, "GOOD"
    )

    assert fake.upserts, "expected the memory to be upserted"
    meta = fake.upserts[0]["metadata"]
    assert meta.get("simulated") is True, "simulated flag must be stamped on the vector"
    assert meta.get("embedding_model"), "embedding model must be stamped for re-embed detection"
    assert meta.get("memory_type") == "DECISION", "existing metadata must be preserved"
