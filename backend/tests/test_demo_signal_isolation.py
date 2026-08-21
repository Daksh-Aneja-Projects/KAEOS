"""H14: simulated (DEMO) connector signals never pollute the real closed loop.

A connector with no credentials produces a simulated feed. Those rows used to
claim signal_type="WEBHOOK" with authority 0.8/0.95 — indistinguishable from,
and out-ranking, genuine pulls. They are now signal_type="DEMO" at authority 0.0
and are excluded from the event-mesh bridge (H1), the RAG embed (H5), and any
authority-floored reader (precog's > 0.8)."""
import pytest
from sqlalchemy import select

from app.models.domain import Signal
from app.models.event_mesh import ExternalSignal
from app.services.event_mesh import ingest_connector_signals
from app.services.live_connectors import LiveConnectorService

TENANT = "tenant_demo_iso"


def _sig(i, stype):
    return Signal(id=f"s{i}", tenant_id=TENANT, signal_type=stype, source_type="jira",
                  source_entity=f"t:{i}", external_id=str(i),
                  clean_payload="engineering security content", authority_score=0.0
                  if stype == "DEMO" else 0.7, domain="engineering")


@pytest.mark.asyncio
async def test_demo_signals_are_not_bridged_into_the_mesh(db):
    signals = [_sig(1, "LIVE_SYNC"), _sig(2, "DEMO"), _sig(3, "DEMO")]
    bridged = await ingest_connector_signals(db, TENANT, signals)
    await db.commit()
    assert bridged == 1, "only the LIVE signal bridges; DEMO is excluded"
    rows = (await db.execute(select(ExternalSignal).where(
        ExternalSignal.tenant_id == TENANT))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_demo_signals_are_not_embedded(monkeypatch):
    class _LLM:
        embeddings_simulated = False
        async def embed(self, texts):
            return [[0.1, 0.2] for _ in texts]

    upserts = []

    class _Store:
        async def upsert(self, **kw):
            upserts.append(kw)

    async def _router(_t):
        return _LLM()

    monkeypatch.setattr("app.services.llm_router.get_tenant_router", _router)
    monkeypatch.setattr("app.core.polystore.get_vector_store", lambda: _Store())

    n = await LiveConnectorService.embed_signals_into_memory(
        TENANT, [_sig(1, "LIVE_SYNC"), _sig(2, "DEMO")])
    assert n == 1 and len(upserts) == 1, "DEMO signals are never embedded for RAG"
