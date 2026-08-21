"""M13: GDPR erasure now reaches the graph store.

erase_subject purged DB rows, blobs and vectors but not polystore_graph_nodes,
so a Knowledge node (name = content[:48]) carrying a subject's PII survived
erasure. The graph store gained delete_subject; here we prove it purges matching
nodes + their edges, tenant-scoped."""
import pytest

from app.core.polystore import get_graph_store


@pytest.mark.asyncio
async def test_graph_delete_subject_is_tenant_scoped_and_detaches_edges():
    gs = get_graph_store()
    await gs.upsert_node("tA", "k1", "Knowledge", {"name": "note about jane@x.com comp"})
    await gs.upsert_node("tA", "k2", "Knowledge", {"name": "unrelated content"})
    await gs.upsert_node("tA", "dept-hr", "Department", {"name": "HR"})
    await gs.upsert_edge("tA", "k1", "dept-hr", "INFORMS", {})
    # Same PII text under another tenant must NOT be touched.
    await gs.upsert_node("tB", "k3", "Knowledge", {"name": "jane@x.com elsewhere"})

    deleted = await gs.delete_subject("tA", ["jane@x.com"])
    assert deleted == 1, "only the matching node in tenant A is deleted"

    nodes_a, edges_a = await gs.snapshot("tA")
    assert "k1" not in nodes_a and "k2" in nodes_a
    assert all(e["source"] != "k1" and e["target"] != "k1" for e in edges_a), \
        "the dangling edge to the deleted node is gone"

    nodes_b, _ = await gs.snapshot("tB")
    assert "k3" in nodes_b, "another tenant's node with the same text survives"


@pytest.mark.asyncio
async def test_graph_delete_subject_empty_terms_is_noop():
    gs = get_graph_store()
    assert await gs.delete_subject("tX", []) == 0
    assert await gs.delete_subject("tX", ["", "  "]) == 0
