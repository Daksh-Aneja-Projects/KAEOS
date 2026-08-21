"""M7: /neural/world is cached, fingerprinted on the counts that change its shape.

The endpoint was the heaviest uncached read (full fan-out + O(agents x messages)
matching + a full graph snapshot). It now runs through result_cache. This locks
that the wrapping is correct — the endpoint still returns a valid graph and a
repeat call is consistent."""
import pytest

from app.api.routes.neural import neural_world


@pytest.mark.asyncio
async def test_world_returns_valid_graph_and_is_repeatable(db):
    r1 = await neural_world(tenant_id="tenant_m7", db=db)
    assert set(r1) >= {"nodes", "edges", "departments", "brain"}
    # The company brain is always present as the center node.
    assert any(n["id"] == "brain" for n in r1["nodes"])

    # Same fingerprint -> a cache hit returns the same shape.
    r2 = await neural_world(tenant_id="tenant_m7", db=db)
    assert len(r2["nodes"]) == len(r1["nodes"])
    assert len(r2["edges"]) == len(r1["edges"])
