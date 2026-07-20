"""KAEOS Polystore — Graph Store abstraction.

Two interchangeable backends:

  * ``Neo4jGraphStore``  — real Neo4j via the official async driver. Used when a
                           Neo4j URI/credentials are configured and reachable.
  * ``SqliteGraphStore`` — durable nodes/edges tables in the app database plus an
                           in-process BFS for dependency/impact traversal. Used on
                           the zero-dependency dev stack.

Selection is driven by ``settings.is_sqlite`` (and Neo4j reachability) via
:func:`get_graph_store`.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_NODES = "polystore_graph_nodes"
_EDGES = "polystore_graph_edges"


class GraphStore(ABC):
    """Abstract enterprise graph store."""

    backend_name: str = "abstract"

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def upsert_node(self, node_id: str, label: str, properties: dict) -> str: ...

    @abstractmethod
    async def upsert_edge(self, source_id: str, target_id: str, rel_type: str, properties: Optional[dict] = None) -> None: ...

    @abstractmethod
    async def traverse_impact(self, node_id: str, max_depth: int = 3) -> list[dict[str, Any]]:
        """Downstream blast radius (follow outgoing edges)."""

    @abstractmethod
    async def traverse_dependencies(self, node_id: str, max_depth: int = 3) -> list[dict[str, Any]]:
        """Upstream dependencies (follow incoming edges)."""

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...


class SqliteGraphStore(GraphStore):
    """Durable graph in the app DB (works on SQLite and Postgres alike)."""

    backend_name = "sqlite"

    async def initialize(self) -> None:
        # DDL on the OWNER engine — the app role cannot CREATE under RLS setups.
        from app.core.database import MaintenanceSessionLocal
        async with MaintenanceSessionLocal() as session:
            await session.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_NODES} ("
                "id TEXT PRIMARY KEY, label TEXT, properties TEXT)"
            ))
            await session.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_EDGES} ("
                "source TEXT, target TEXT, rel_type TEXT, properties TEXT)"
            ))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_EDGES}_source ON {_EDGES}(source)"
            ))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_EDGES}_target ON {_EDGES}(target)"
            ))
            await session.commit()

    async def upsert_node(self, node_id, label, properties) -> str:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    f"INSERT INTO {_NODES} (id, label, properties) VALUES (:id, :label, :props) "  # nosec B608
                    "ON CONFLICT(id) DO UPDATE SET label=excluded.label, properties=excluded.properties"
                ),
                {"id": node_id, "label": label, "props": json.dumps({**(properties or {}), "id": node_id})},
            )
            await session.commit()
        return node_id

    async def upsert_edge(self, source_id, target_id, rel_type, properties=None) -> None:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            # De-dupe identical edges.
            existing = await session.execute(
                text(
                    f"SELECT 1 FROM {_EDGES} WHERE source=:s AND target=:t AND rel_type=:r"  # nosec B608
                ),
                {"s": source_id, "t": target_id, "r": rel_type},
            )
            if existing.first() is None:
                await session.execute(
                    text(
                        f"INSERT INTO {_EDGES} (source, target, rel_type, properties) "  # nosec B608
                        "VALUES (:s, :t, :r, :p)"
                    ),
                    {"s": source_id, "t": target_id, "r": rel_type, "p": json.dumps(properties or {})},
                )
                await session.commit()

    async def _load(self) -> tuple[dict, list]:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            n = await session.execute(text(f"SELECT id, label, properties FROM {_NODES}"))  # nosec B608
            e = await session.execute(text(f"SELECT source, target, rel_type FROM {_EDGES}"))  # nosec B608
            nodes = {}
            for row in n.mappings().all():
                try:
                    props = json.loads(row["properties"]) if row["properties"] else {}
                except (ValueError, TypeError):
                    props = {}
                nodes[row["id"]] = {"id": row["id"], "label": row["label"], **props}
            edges = [{"source": r["source"], "target": r["target"], "type": r["rel_type"]}
                     for r in e.mappings().all()]
        return nodes, edges

    async def traverse_impact(self, node_id, max_depth=3) -> list[dict[str, Any]]:
        nodes, edges = await self._load()
        start = nodes.get(node_id)
        if not start:
            return []
        results, visited = [], {node_id}
        queue = [(node_id, [start], [])]
        while queue:
            curr, p_nodes, p_rels = queue.pop(0)
            if len(p_nodes) - 1 >= max_depth:
                continue
            for edge in edges:
                if edge["source"] == curr and edge["target"] not in visited:
                    visited.add(edge["target"])
                    tgt = nodes.get(edge["target"])
                    if tgt:
                        np, nr = p_nodes + [tgt], p_rels + [{"type": edge["type"]}]
                        results.append({"downstream": tgt, "path_nodes": np, "path_rels": nr})
                        queue.append((edge["target"], np, nr))
        return results

    async def traverse_dependencies(self, node_id, max_depth=3) -> list[dict[str, Any]]:
        nodes, edges = await self._load()
        start = nodes.get(node_id)
        if not start:
            return []
        results, visited = [], {node_id}
        queue = [(node_id, [start], [])]
        while queue:
            curr, p_nodes, p_rels = queue.pop(0)
            if len(p_nodes) - 1 >= max_depth:
                continue
            for edge in edges:
                if edge["target"] == curr and edge["source"] not in visited:
                    visited.add(edge["source"])
                    src = nodes.get(edge["source"])
                    if src:
                        np, nr = p_nodes + [src], p_rels + [{"type": edge["type"]}]
                        results.append({"upstream": src, "path_nodes": np, "path_rels": nr})
                        queue.append((edge["source"], np, nr))
        return results

    async def health(self) -> dict[str, Any]:
        try:
            nodes, edges = await self._load()
            return {"backend": self.backend_name, "available": True,
                    "nodes": len(nodes), "edges": len(edges)}
        except Exception as e:
            return {"backend": self.backend_name, "available": False, "error": str(e)}


class Neo4jGraphStore(GraphStore):
    """Real Neo4j graph store (async driver). Degrades gracefully if unreachable."""

    backend_name = "neo4j"

    def __init__(self, uri: str, user: str, password: str):
        self._uri, self._user, self._password = uri, user, password
        self._driver = None

    async def initialize(self) -> None:
        if self._driver is not None:
            return
        from neo4j import AsyncGraphDatabase  # type: ignore
        self._driver = AsyncGraphDatabase.driver(self._uri, auth=(self._user, self._password))

    async def upsert_node(self, node_id, label, properties) -> str:
        await self.initialize()
        props = {**(properties or {}), "id": node_id}
        async with self._driver.session() as s:
            await s.run(
                f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                id=node_id, props=props,
            )
        return node_id

    async def upsert_edge(self, source_id, target_id, rel_type, properties=None) -> None:
        await self.initialize()
        async with self._driver.session() as s:
            await s.run(
                "MATCH (a {id: $s}), (b {id: $t}) "
                f"MERGE (a)-[r:{rel_type}]->(b) SET r += $props",
                s=source_id, t=target_id, props=properties or {},
            )

    async def traverse_impact(self, node_id, max_depth=3) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._driver.session() as s:
            res = await s.run(
                f"MATCH path = (n {{id: $id}})-[*1..{int(max_depth)}]->(m) RETURN m, path",
                id=node_id,
            )
            return [{"downstream": dict(rec["m"])} async for rec in res]

    async def traverse_dependencies(self, node_id, max_depth=3) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._driver.session() as s:
            res = await s.run(
                f"MATCH path = (m)-[*1..{int(max_depth)}]->(n {{id: $id}}) RETURN m, path",
                id=node_id,
            )
            return [{"upstream": dict(rec["m"])} async for rec in res]

    async def health(self) -> dict[str, Any]:
        try:
            await self.initialize()
            async with self._driver.session() as s:
                await s.run("RETURN 1")
            return {"backend": self.backend_name, "available": True, "uri": self._uri}
        except Exception as e:
            return {"backend": self.backend_name, "available": False, "error": str(e)}


_graph_store: Optional[GraphStore] = None


def get_graph_store() -> GraphStore:
    """Return the process-wide GraphStore.

    Uses Neo4j when the app is on a non-SQLite DB and a Neo4j password is set;
    otherwise the durable SQLite graph store. Falls back to SQLite if the Neo4j
    driver is not installed.
    """
    global _graph_store
    if _graph_store is None:
        settings = get_settings()
        use_neo4j = (not settings.is_sqlite) and bool(settings.NEO4J_PASSWORD)
        if use_neo4j:
            try:
                import neo4j  # noqa: F401
                _graph_store = Neo4jGraphStore(
                    settings.NEO4J_URI, settings.NEO4J_USER, settings.NEO4J_PASSWORD
                )
            except ImportError:
                logger.warning("[Polystore] neo4j driver not installed — using SQLite graph store")
                _graph_store = SqliteGraphStore()
        else:
            _graph_store = SqliteGraphStore()
        logger.info(f"[Polystore] GraphStore backend = {_graph_store.backend_name}")
    return _graph_store
