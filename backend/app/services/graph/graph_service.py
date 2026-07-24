"""
KAEOS Enterprise Graph Service
High-level facade over the real polystore GraphStore.

This service used to sit on a hand-rolled in-memory "Neo4j" provider that never
opened a Neo4j connection (``services/graph/neo4j_client.py`` — deleted). It now
delegates to the single, real graph backend selected by
``app.core.polystore.graph_store.get_graph_store()``:

  * ``SqliteGraphStore`` — durable nodes/edges tables in the app DB (dev stack), or
  * ``Neo4jGraphStore``  — real Neo4j via the async driver (prod, when configured).

The public method names are unchanged so existing callers (ImpactPropagationEngine,
ScorecardEngine, EnterpriseFitnessCalculator, SyntheticEnterpriseGenerator) keep
working — only the backend became real.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.core.polystore.graph_store import GraphStore, get_graph_store


class GraphService:
    def __init__(self, store: Optional[GraphStore] = None):
        # ``store`` override is retained for tests/DI; production resolves the
        # process-wide real store (SQLite durable or Neo4j) via the polystore.
        self.store: GraphStore = store or get_graph_store()

    async def initialize(self):
        await self.store.initialize()

    async def shutdown(self):
        # The polystore stores manage their own lifecycle; close the Neo4j driver
        # if the active backend exposes one.
        driver = getattr(self.store, "_driver", None)
        if driver is not None:
            try:
                await driver.close()
            except Exception:
                pass

    async def register_entity(self, entity_id: str, label: str, properties: Dict[str, Any]):
        """Register (upsert) a node in the graph. ``id`` is forced to ``entity_id``."""
        props = dict(properties or {})
        props["id"] = entity_id
        await self.store.upsert_node(entity_id, label, props)

    async def update_entity(self, entity_id: str, label: str, properties: Dict[str, Any]):
        """Update a node's properties (upsert semantics)."""
        await self.store.upsert_node(entity_id, label, dict(properties or {}))

    async def link_entities(self, source_id: str, target_id: str, relation: str,
                            properties: Dict[str, Any] = None):
        """Create a directed relationship between two entities."""
        await self.store.upsert_edge(source_id, target_id, relation, properties)

    async def get_impact_radius(self, entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
        """Downstream blast radius (follow outgoing edges)."""
        return await self.store.traverse_impact(entity_id, depth)

    async def get_dependencies(self, entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
        """Upstream dependencies (follow incoming edges)."""
        return await self.store.traverse_dependencies(entity_id, depth)

    async def snapshot(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Whole-graph ``(nodes_by_id, edges)`` for aggregate analytics."""
        return await self.store.snapshot()

    async def health(self) -> Dict[str, Any]:
        return await self.store.health()
