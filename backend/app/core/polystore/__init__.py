"""KAEOS Polystore — dual-mode persistence abstraction.

A single seam over the three stateful backends the platform depends on, each with
a production implementation and a zero-dependency dev-stack fallback selected at
runtime:

  * VectorStore : pgvector  <-> SQLite (in-process cosine)
  * GraphStore  : Neo4j     <-> SQLite (nodes/edges + BFS)
  * CacheBus    : Redis      <-> in-memory (TTL + asyncio pub/sub)

Backend selection keys off ``settings.is_sqlite`` (and service reachability).
Use the factories below; call :func:`polystore_health` for a status snapshot that
``/health`` surfaces.
"""
from app.core.polystore.vector_store import (
    VectorStore, PgVectorStore, SqliteVectorStore, get_vector_store,
)
from app.core.polystore.graph_store import (
    GraphStore, Neo4jGraphStore, SqliteGraphStore, get_graph_store,
)
from app.core.polystore.cache_bus import (
    CacheBus, RedisCacheBus, MemoryCacheBus, get_cache_bus, reset_cache_bus,
)

__all__ = [
    "VectorStore", "PgVectorStore", "SqliteVectorStore", "get_vector_store",
    "GraphStore", "Neo4jGraphStore", "SqliteGraphStore", "get_graph_store",
    "CacheBus", "RedisCacheBus", "MemoryCacheBus", "get_cache_bus", "reset_cache_bus",
    "polystore_health",
]


async def polystore_health() -> dict:
    """Return the active backend + availability for each polystore component."""
    vector = await get_vector_store().health()
    graph = await get_graph_store().health()
    cache = await (await get_cache_bus()).health()
    return {
        "vector_store": vector,
        "graph_store": graph,
        "cache_bus": cache,
    }
