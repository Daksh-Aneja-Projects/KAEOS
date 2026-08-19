"""KAEOS Polystore — Graph Store abstraction.

Two interchangeable backends:

  * ``Neo4jGraphStore``  — real Neo4j via the official async driver. Used when a
                           Neo4j URI/credentials are configured and reachable.
  * ``SqliteGraphStore`` — durable nodes/edges tables in the app database plus an
                           in-process BFS for dependency/impact traversal. Used on
                           the zero-dependency dev stack.

Selection is driven by ``settings.is_sqlite`` (and Neo4j reachability) via
:func:`get_graph_store`.

DELIBERATELY OUTSIDE ALEMBIC AND Base.metadata
----------------------------------------------
``polystore_graph_nodes`` / ``polystore_graph_edges`` are created lazily by
``initialize()`` below, not by a migration and not by an ORM model — same as
``polystore_vectors`` in vector_store.py. Kept that way on purpose: under the
Neo4j backend these tables do not exist at all, so a migration would create dead
tables for half the deployments, and the rows are regenerable derived structure
with nothing to preserve. ``initialize()`` also performs its own repair (dropping
a pre-tenant-scoped table and rebuilding it), which is migration work that has to
run per-backend anyway.

What a schema checker needs to know: these tables exist in a live database but in
NEITHER ``Base.metadata`` NOR any migration, so a check diffing those two sources
against a running DB must treat them as a known exemption, not drift. The
tenant_id column, RLS policy and indexes are all installed here at create time,
so the exemption costs no isolation.
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
    async def upsert_node(self, tenant_id: str, node_id: str, label: str, properties: dict) -> str: ...

    @abstractmethod
    async def upsert_edge(self, tenant_id: str, source_id: str, target_id: str, rel_type: str, properties: Optional[dict] = None) -> None: ...

    @abstractmethod
    async def traverse_impact(self, tenant_id: str, node_id: str, max_depth: int = 3) -> list[dict[str, Any]]:
        """Downstream blast radius (follow outgoing edges), within one tenant."""

    @abstractmethod
    async def traverse_dependencies(self, tenant_id: str, node_id: str, max_depth: int = 3) -> list[dict[str, Any]]:
        """Upstream dependencies (follow incoming edges), within one tenant."""

    @abstractmethod
    async def snapshot(self, tenant_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return ONE TENANT's graph as ``(nodes_by_id, edges)`` for analytics.

        ``nodes_by_id`` maps node id -> ``{"id", "label", **properties}``.
        ``edges`` is a list of ``{"source", "target", "type"}`` dicts. Used by
        engines that need aggregate structure (fitness, scorecard) rather than a
        single-node traversal. Every returned row belongs to ``tenant_id``.
        """

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...


class SqliteGraphStore(GraphStore):
    """Durable, TENANT-SCOPED graph in the app DB (SQLite and Postgres alike).

    Every node/edge carries a ``tenant_id`` and every read/write is filtered by
    it, so one tenant can never see or traverse into another tenant's graph.
    Node ids are unique *per tenant* (composite primary key), so two tenants may
    reuse the same id without colliding. On Postgres the tables are additionally
    placed under row-level security as a backstop.
    """

    backend_name = "sqlite"

    def __init__(self) -> None:
        self._ready = False

    async def initialize(self) -> None:
        if self._ready:
            return
        # DDL on the OWNER engine — the app role cannot CREATE under RLS setups.
        from app.core.database import MaintenanceSessionLocal
        async with MaintenanceSessionLocal() as session:
            dialect = session.bind.dialect.name
            # Tables that predate tenant scoping have no tenant_id column and
            # therefore leak across tenants. The graph holds derived/regenerable
            # structure, so the safe migration is to drop the untenanted table
            # and recreate it tenant-scoped rather than serve orphaned rows.
            for tbl in (_NODES, _EDGES):
                if await self._table_missing_tenant(session, tbl, dialect):
                    await session.execute(text(f"DROP TABLE IF EXISTS {tbl}"))  # nosec B608
                    logger.warning(
                        "[Polystore] dropped pre-tenant %s (no tenant_id column) — "
                        "recreating tenant-scoped", tbl,
                    )
            await session.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_NODES} ("
                "tenant_id TEXT NOT NULL, id TEXT NOT NULL, label TEXT, properties TEXT, "
                "PRIMARY KEY (tenant_id, id))"
            ))
            await session.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_EDGES} ("
                "tenant_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, "
                "rel_type TEXT, properties TEXT)"
            ))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_EDGES}_src ON {_EDGES}(tenant_id, source)"
            ))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_EDGES}_tgt ON {_EDGES}(tenant_id, target)"
            ))
            await session.commit()
            # Postgres backstop: these tables are created lazily (after the
            # init_db RLS sweep), so enable isolation here too. Idempotent.
            if dialect == "postgresql":
                from app.core.rls import rls_enable_statements
                for tbl in (_NODES, _EDGES):
                    for stmt in rls_enable_statements(tbl):
                        await session.execute(text(stmt))
                await session.commit()
        self._ready = True

    @staticmethod
    async def _table_missing_tenant(session, table: str, dialect: str) -> bool:
        """True only if ``table`` EXISTS and lacks a ``tenant_id`` column."""
        if dialect == "sqlite":
            rows = (await session.execute(text(f"PRAGMA table_info({table})"))).all()  # nosec B608
            if not rows:
                return False  # doesn't exist yet — nothing to migrate
            return "tenant_id" not in {r[1] for r in rows}
        # Postgres
        exists = (await session.execute(
            text("SELECT 1 FROM information_schema.tables "
                 "WHERE table_schema='public' AND table_name=:t"), {"t": table}
        )).first()
        if not exists:
            return False
        has_col = (await session.execute(
            text("SELECT 1 FROM information_schema.columns "
                 "WHERE table_schema='public' AND table_name=:t AND column_name='tenant_id'"),
            {"t": table},
        )).first()
        return has_col is None

    async def upsert_node(self, tenant_id, node_id, label, properties) -> str:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    f"INSERT INTO {_NODES} (tenant_id, id, label, properties) "  # nosec B608
                    "VALUES (:tid, :id, :label, :props) "
                    "ON CONFLICT(tenant_id, id) DO UPDATE SET label=excluded.label, properties=excluded.properties"
                ),
                {"tid": tenant_id, "id": node_id, "label": label,
                 "props": json.dumps({**(properties or {}), "id": node_id})},
            )
            await session.commit()
        return node_id

    async def upsert_edge(self, tenant_id, source_id, target_id, rel_type, properties=None) -> None:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            # De-dupe identical edges within the tenant.
            existing = await session.execute(
                text(
                    f"SELECT 1 FROM {_EDGES} WHERE tenant_id=:tid AND source=:s AND target=:t AND rel_type=:r"  # nosec B608
                ),
                {"tid": tenant_id, "s": source_id, "t": target_id, "r": rel_type},
            )
            if existing.first() is None:
                await session.execute(
                    text(
                        f"INSERT INTO {_EDGES} (tenant_id, source, target, rel_type, properties) "  # nosec B608
                        "VALUES (:tid, :s, :t, :r, :p)"
                    ),
                    {"tid": tenant_id, "s": source_id, "t": target_id, "r": rel_type,
                     "p": json.dumps(properties or {})},
                )
                await session.commit()

    async def _load(self, tenant_id: str) -> tuple[dict, list]:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            n = await session.execute(
                text(f"SELECT id, label, properties FROM {_NODES} WHERE tenant_id=:tid"),  # nosec B608
                {"tid": tenant_id},
            )
            e = await session.execute(
                text(f"SELECT source, target, rel_type FROM {_EDGES} WHERE tenant_id=:tid"),  # nosec B608
                {"tid": tenant_id},
            )
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

    async def traverse_impact(self, tenant_id, node_id, max_depth=3) -> list[dict[str, Any]]:
        nodes, edges = await self._load(tenant_id)
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

    async def traverse_dependencies(self, tenant_id, node_id, max_depth=3) -> list[dict[str, Any]]:
        nodes, edges = await self._load(tenant_id)
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

    async def snapshot(self, tenant_id) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return await self._load(tenant_id)

    async def health(self) -> dict[str, Any]:
        # Ops probe: total row counts across tenants (no per-tenant data returned).
        # Uses the owner session so RLS does not hide the true totals on Postgres.
        try:
            await self.initialize()
            from app.core.database import MaintenanceSessionLocal
            async with MaintenanceSessionLocal() as session:
                nc = (await session.execute(text(f"SELECT count(*) FROM {_NODES}"))).scalar() or 0  # nosec B608
                ec = (await session.execute(text(f"SELECT count(*) FROM {_EDGES}"))).scalar() or 0  # nosec B608
            return {"backend": self.backend_name, "available": True,
                    "nodes": int(nc), "edges": int(ec)}
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

    async def upsert_node(self, tenant_id, node_id, label, properties) -> str:
        await self.initialize()
        # Store ``label`` and ``tenant_id`` as properties too so snapshot() is
        # uniform with the SQLite backend and every match can be tenant-scoped.
        # MERGE keys on (tenant_id, id) so two tenants may reuse the same id.
        props = {**(properties or {}), "id": node_id, "label": label, "tenant_id": tenant_id}
        async with self._driver.session() as s:
            await s.run(
                f"MERGE (n:{label} {{id: $id, tenant_id: $tid}}) SET n += $props",
                id=node_id, tid=tenant_id, props=props,
            )
        return node_id

    async def upsert_edge(self, tenant_id, source_id, target_id, rel_type, properties=None) -> None:
        await self.initialize()
        props = {**(properties or {}), "tenant_id": tenant_id}
        async with self._driver.session() as s:
            await s.run(
                "MATCH (a {id: $s, tenant_id: $tid}), (b {id: $t, tenant_id: $tid}) "
                f"MERGE (a)-[r:{rel_type}]->(b) SET r += $props",
                s=source_id, t=target_id, tid=tenant_id, props=props,
            )

    async def traverse_impact(self, tenant_id, node_id, max_depth=3) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._driver.session() as s:
            res = await s.run(
                f"MATCH path = (n {{id: $id, tenant_id: $tid}})-[*1..{int(max_depth)}]->"
                "(m {tenant_id: $tid}) RETURN m, path",
                id=node_id, tid=tenant_id,
            )
            return [{"downstream": dict(rec["m"])} async for rec in res]

    async def traverse_dependencies(self, tenant_id, node_id, max_depth=3) -> list[dict[str, Any]]:
        await self.initialize()
        async with self._driver.session() as s:
            res = await s.run(
                f"MATCH path = (m {{tenant_id: $tid}})-[*1..{int(max_depth)}]->"
                "(n {id: $id, tenant_id: $tid}) RETURN m, path",
                id=node_id, tid=tenant_id,
            )
            return [{"upstream": dict(rec["m"])} async for rec in res]

    async def snapshot(self, tenant_id) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        await self.initialize()
        nodes: dict[str, Any] = {}
        edges: list[dict[str, Any]] = []
        async with self._driver.session() as s:
            res = await s.run("MATCH (n {tenant_id: $tid}) RETURN n", tid=tenant_id)
            async for rec in res:
                n = dict(rec["n"])
                nid = n.get("id")
                if nid is not None:
                    nodes[nid] = n
            res2 = await s.run(
                "MATCH (a {tenant_id: $tid})-[r]->(b {tenant_id: $tid}) "
                "RETURN a.id AS source, b.id AS target, type(r) AS rel_type",
                tid=tenant_id,
            )
            async for rec in res2:
                edges.append({"source": rec["source"], "target": rec["target"], "type": rec["rel_type"]})
        return nodes, edges

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
