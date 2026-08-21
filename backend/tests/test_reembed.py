"""M14: stale-vector detection + the re-embed job's honest behavior.

- stale_vectors returns only vectors stamped with a different (or missing)
  embedding model, tenant-scoped; current-model rows never match.
- reembed_stale_vectors either genuinely refreshes a stale vector (real
  embedder) or refuses and leaves it stale (simulated-only router) - it must
  never stamp a vector current without re-embedding it.
"""
import pytest

from app.core.polystore import get_vector_store
from app.services.knowledge import reembed_stale_vectors
from app.services.llm_support import configured_embedding_model


@pytest.mark.asyncio
async def test_stale_vectors_filters_on_model_stamp():
    store = get_vector_store()
    current = configured_embedding_model()
    await store.upsert(vector_id="re-old-1", tenant_id="tR", content="alpha",
                       embedding=[0.1, 0.2], metadata={"embedding_model": "ancient-model"})
    # Unstamped predates stamping entirely - counts as stale.
    await store.upsert(vector_id="re-old-2", tenant_id="tR", content="beta",
                       embedding=[0.3, 0.4], metadata={})
    await store.upsert(vector_id="re-new-1", tenant_id="tR", content="gamma",
                       embedding=[0.5, 0.6], metadata={"embedding_model": current})
    # Another tenant's stale vector must not leak into this tenant's sweep.
    await store.upsert(vector_id="re-other", tenant_id="tOTHER", content="delta",
                       embedding=[0.7, 0.8], metadata={"embedding_model": "ancient-model"})

    stale = await store.stale_vectors("tR", current_model=current)
    ids = {v["id"] for v in stale}
    assert ids == {"re-old-1", "re-old-2"}, ids


@pytest.mark.asyncio
async def test_reembed_refreshes_or_honestly_refuses():
    store = get_vector_store()
    current = configured_embedding_model()
    await store.upsert(vector_id="re-job-1", tenant_id="tReembed", content="needs refresh",
                       embedding=[0.1, 0.2], metadata={"embedding_model": "ancient-model"})

    receipt = await reembed_stale_vectors("tReembed")
    if receipt["embeddings_simulated"]:
        # A pseudo-vector rewrite buys nothing: refuse before touching anything.
        assert receipt["reembedded"] == 0
        still = {v["id"] for v in await store.stale_vectors("tReembed", current_model=current)}
        assert "re-job-1" in still, "a refusal must leave the vector visibly stale"
    else:
        # A real embedder refreshed it against the model the router ACTUALLY
        # uses (which may differ from the configured name).
        assert receipt["stale_found"] >= 1
        assert receipt["reembedded"] >= 1
        effective = receipt["current_model"]
        assert effective
        again = {v["id"] for v in await store.stale_vectors("tReembed", current_model=effective)}
        assert "re-job-1" not in again
