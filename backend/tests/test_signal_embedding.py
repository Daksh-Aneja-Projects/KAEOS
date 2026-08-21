"""H5: connector signals are embedded into the enterprise-memory namespace so
chat RAG grounds on real connector data instead of an empty corpus.

Tests run with simulated embeddings by default, so the real-model path is
exercised with a fake router/store."""
import pytest

from app.models.domain import Signal
from app.services.live_connectors import LiveConnectorService

TENANT = "tenant_embed"


class _FakeStore:
    def __init__(self):
        self.upserts = []

    async def upsert(self, **kw):
        self.upserts.append(kw)


def _sig(i, payload, stype="LIVE_SYNC"):
    return Signal(id=f"s{i}", tenant_id=TENANT, signal_type=stype, source_type="jira",
                  source_entity=f"t:{i}", external_id=str(i), clean_payload=payload,
                  authority_score=0.7, domain="engineering")


@pytest.mark.asyncio
async def test_embed_skips_quarantined_and_empty_and_uses_memory_namespace(monkeypatch):
    class _LLM:
        embeddings_simulated = False
        async def embed(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    store = _FakeStore()

    async def _router(_tid):
        return _LLM()

    monkeypatch.setattr("app.services.llm_router.get_tenant_router", _router)
    monkeypatch.setattr("app.core.polystore.get_vector_store", lambda: store)

    sigs = [
        _sig(1, "real engineering content"),
        _sig(2, "injection payload", stype="QUARANTINED"),
        _sig(3, "   "),  # empty after strip
    ]
    n = await LiveConnectorService.embed_signals_into_memory(TENANT, sigs)

    assert n == 1, "only the real, non-empty, non-quarantined signal embeds"
    assert len(store.upserts) == 1
    up = store.upserts[0]
    assert up["namespace"] == "enterprise_memory"
    assert up["vector_id"] == "connector-sig-s1"
    assert up["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_embed_is_noop_when_embeddings_simulated(monkeypatch):
    class _SimLLM:
        embeddings_simulated = True
        async def embed(self, texts):
            return [[0.0] for _ in texts]

    store = _FakeStore()

    async def _router(_tid):
        return _SimLLM()

    monkeypatch.setattr("app.services.llm_router.get_tenant_router", _router)
    monkeypatch.setattr("app.core.polystore.get_vector_store", lambda: store)

    n = await LiveConnectorService.embed_signals_into_memory(TENANT, [_sig(1, "x")])
    assert n == 0 and store.upserts == [], "no real model -> nothing embedded"
