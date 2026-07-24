"""KAEOS Polystore — Vector Store abstraction.

Provides a single async interface for semantic vector storage/recall with two
interchangeable backends selected at runtime:

  * ``PgVectorStore``   — PostgreSQL + pgvector (``embedding vector`` column, ``<=>``
                          cosine-distance operator). Used when the app runs on Postgres.
  * ``SqliteVectorStore`` — SQLite (embedding stored as a JSON list; cosine similarity
                          computed in-process). Used on the zero-dependency dev stack.

Selection is driven by ``settings.is_sqlite`` via :func:`get_vector_store`.
Both backends share a self-contained ``polystore_vectors`` table created lazily,
so no external migration is required.
"""
from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TABLE = "polystore_vectors"


class VectorStore(ABC):
    """Abstract semantic vector store."""

    backend_name: str = "abstract"

    @abstractmethod
    async def initialize(self) -> None:
        """Create backing storage if it does not yet exist."""

    @abstractmethod
    async def upsert(
        self,
        vector_id: str,
        tenant_id: str,
        content: str,
        embedding: list[float],
        metadata: Optional[dict] = None,
        namespace: str = "default",
    ) -> None:
        """Insert or replace a vector record."""

    @abstractmethod
    async def search(
        self,
        tenant_id: str,
        query_embedding: list[float],
        limit: int = 5,
        namespace: str = "default",
    ) -> list[dict[str, Any]]:
        """Return the ``limit`` most similar records (cosine), each with a
        ``similarity`` float in ``[-1, 1]``."""

    @abstractmethod
    async def update_metadata(self, vector_id: str, key: str, value: Any) -> None:
        """Patch a single key on a record's metadata JSON."""

    @abstractmethod
    async def delete_subject(
        self,
        tenant_id: str,
        *,
        subject_ids: Optional[list[str]] = None,
        subject_texts: Optional[list[str]] = None,
    ) -> int:
        """Delete every vector for ``tenant_id`` that references a data subject.

        Matches any of ``subject_ids`` (e.g. employee/candidate id) or
        ``subject_texts`` (e.g. an email) appearing in the record's metadata or
        content. Returns the number of embeddings deleted. Used by GDPR Art.17
        erasure so a subject's embeddings do not survive in the vector layer.
        """

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"backend": ..., "available": bool, ...}``."""


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class SqliteVectorStore(VectorStore):
    """SQLite-backed vector store. Embeddings are stored as JSON text and cosine
    similarity is computed in-process (fine for dev / modest corpora)."""

    backend_name = "sqlite"

    _DDL = f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            namespace TEXT NOT NULL DEFAULT 'default',
            content TEXT,
            metadata TEXT,
            embedding TEXT,
            created_at TEXT
        )
    """

    async def initialize(self) -> None:
        # DDL is a maintenance operation: under Postgres RLS the app role
        # (kaeos_app) deliberately cannot CREATE in schema public, so this must
        # run on the owner engine. On SQLite the two engines are the same.
        from app.core.database import MaintenanceSessionLocal
        async with MaintenanceSessionLocal() as session:
            await session.execute(text(self._DDL))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant ON {_TABLE}(tenant_id, namespace)"
            ))
            await session.commit()

    async def upsert(self, vector_id, tenant_id, content, embedding, metadata=None, namespace="default") -> None:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    f"INSERT INTO {_TABLE} (id, tenant_id, namespace, content, metadata, embedding, created_at) "  # nosec B608
                    "VALUES (:id, :tenant_id, :namespace, :content, :metadata, :embedding, :created_at) "
                    "ON CONFLICT(id) DO UPDATE SET content=excluded.content, metadata=excluded.metadata, "
                    "embedding=excluded.embedding"
                ),
                {
                    "id": vector_id,
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "content": content,
                    "metadata": json.dumps(metadata or {}),
                    "embedding": json.dumps(list(embedding)),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            await session.commit()

    async def search(self, tenant_id, query_embedding, limit=5, namespace="default") -> list[dict[str, Any]]:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    f"SELECT id, content, metadata, embedding FROM {_TABLE} "  # nosec B608
                    "WHERE tenant_id = :tenant_id AND namespace = :namespace"
                ),
                {"tenant_id": tenant_id, "namespace": namespace},
            )
            rows = result.mappings().all()

        scored = []
        for r in rows:
            try:
                emb = json.loads(r["embedding"]) if r["embedding"] else []
            except (ValueError, TypeError):
                emb = []
            sim = _cosine(query_embedding, emb)
            try:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
            except (ValueError, TypeError):
                meta = {}
            scored.append({
                "id": r["id"],
                "content": r["content"],
                "metadata": meta,
                "similarity": sim,
            })
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    async def update_metadata(self, vector_id, key, value) -> None:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"SELECT metadata FROM {_TABLE} WHERE id = :id"), {"id": vector_id}  # nosec B608
            )
            row = result.first()
            if not row:
                return
            try:
                meta = json.loads(row[0]) if row[0] else {}
            except (ValueError, TypeError):
                meta = {}
            meta[key] = value
            await session.execute(
                text(f"UPDATE {_TABLE} SET metadata = :metadata WHERE id = :id"),  # nosec B608
                {"metadata": json.dumps(meta), "id": vector_id},
            )
            await session.commit()

    async def delete_subject(self, tenant_id, *, subject_ids=None, subject_texts=None) -> int:
        await self.initialize()
        terms = [str(s) for s in (subject_ids or []) if s] + [str(s) for s in (subject_texts or []) if s]
        if not terms:
            return 0
        clauses, params = [], {"tenant_id": tenant_id}
        for i, term in enumerate(terms):
            params[f"t{i}"] = f"%{term}%"
            clauses.append(f"(metadata LIKE :t{i} OR content LIKE :t{i})")
        where = " OR ".join(clauses)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                text(f"DELETE FROM {_TABLE} WHERE tenant_id = :tenant_id AND ({where})"),  # nosec B608
                params,
            )
            await session.commit()
            return int(res.rowcount or 0)

    async def health(self) -> dict[str, Any]:
        try:
            await self.initialize()
            async with AsyncSessionLocal() as session:
                res = await session.execute(text(f"SELECT COUNT(*) FROM {_TABLE}"))  # nosec B608
                count = res.scalar() or 0
            return {"backend": self.backend_name, "available": True, "records": count}
        except Exception as e:  # pragma: no cover - defensive
            return {"backend": self.backend_name, "available": False, "error": str(e)}


class PgVectorStore(VectorStore):
    """PostgreSQL + pgvector store using the native ``<=>`` cosine-distance operator."""

    backend_name = "pgvector"

    def __init__(self, dim: int = 1536):
        self.dim = dim

    async def initialize(self) -> None:
        # DDL runs on the OWNER engine: the app role (kaeos_app) cannot CREATE
        # in schema public under the RLS setup, by design. And because this
        # table is created at runtime — after the RLS migration has already
        # swept information_schema — the migration never saw it, so the tenant
        # isolation policy must be installed here or the table ships without it.
        from app.core.database import MaintenanceSessionLocal
        async with MaintenanceSessionLocal() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.execute(text(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    namespace TEXT NOT NULL DEFAULT 'default',
                    content TEXT,
                    metadata JSONB,
                    embedding vector({self.dim}),
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """
            ))
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant ON {_TABLE}(tenant_id, namespace)"
            ))
            await session.execute(text(f'ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY'))
            await session.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}'))
            await session.execute(text(f"""
                CREATE POLICY tenant_isolation ON {_TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true))
                    WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
            """))
            await session.commit()

    async def upsert(self, vector_id, tenant_id, content, embedding, metadata=None, namespace="default") -> None:
        await self.initialize()
        vec_literal = "[" + ",".join(str(float(x)) for x in embedding) + "]"
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    f"INSERT INTO {_TABLE} (id, tenant_id, namespace, content, metadata, embedding) "  # nosec B608
                    "VALUES (:id, :tenant_id, :namespace, :content, CAST(:metadata AS JSONB), CAST(:embedding AS vector)) "
                    "ON CONFLICT(id) DO UPDATE SET content=excluded.content, metadata=excluded.metadata, "
                    "embedding=excluded.embedding"
                ),
                {
                    "id": vector_id,
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "content": content,
                    "metadata": json.dumps(metadata or {}),
                    "embedding": vec_literal,
                },
            )
            await session.commit()

    async def search(self, tenant_id, query_embedding, limit=5, namespace="default") -> list[dict[str, Any]]:
        await self.initialize()
        vec_literal = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    f"SELECT id, content, metadata, 1 - (embedding <=> CAST(:q AS vector)) AS similarity "  # nosec B608
                    f"FROM {_TABLE} WHERE tenant_id = :tenant_id AND namespace = :namespace "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :limit"
                ),
                {"q": vec_literal, "tenant_id": tenant_id, "namespace": namespace, "limit": limit},
            )
            rows = result.mappings().all()
        out = []
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            out.append({
                "id": r["id"],
                "content": r["content"],
                "metadata": meta or {},
                "similarity": float(r["similarity"]) if r["similarity"] is not None else 0.0,
            })
        return out

    async def update_metadata(self, vector_id, key, value) -> None:
        await self.initialize()
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    f"UPDATE {_TABLE} SET metadata = jsonb_set(COALESCE(metadata, '{{}}'::jsonb), "  # nosec B608
                    "ARRAY[:key], to_jsonb(:value::text)) WHERE id = :id"
                ),
                {"key": key, "value": str(value), "id": vector_id},
            )
            await session.commit()

    async def delete_subject(self, tenant_id, *, subject_ids=None, subject_texts=None) -> int:
        await self.initialize()
        terms = [str(s) for s in (subject_ids or []) if s] + [str(s) for s in (subject_texts or []) if s]
        if not terms:
            return 0
        clauses, params = [], {"tenant_id": tenant_id}
        for i, term in enumerate(terms):
            params[f"t{i}"] = f"%{term}%"
            # metadata is JSONB on Postgres; cast to text for substring match.
            clauses.append(f"(metadata::text LIKE :t{i} OR content LIKE :t{i})")
        where = " OR ".join(clauses)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                text(f"DELETE FROM {_TABLE} WHERE tenant_id = :tenant_id AND ({where})"),  # nosec B608
                params,
            )
            await session.commit()
            return int(res.rowcount or 0)

    async def health(self) -> dict[str, Any]:
        try:
            await self.initialize()
            async with AsyncSessionLocal() as session:
                res = await session.execute(text(f"SELECT COUNT(*) FROM {_TABLE}"))  # nosec B608
                count = res.scalar() or 0
            return {"backend": self.backend_name, "available": True, "records": count}
        except Exception as e:
            return {"backend": self.backend_name, "available": False, "error": str(e)}


_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Return the process-wide VectorStore, selected by ``settings.is_sqlite``."""
    global _vector_store
    if _vector_store is None:
        settings = get_settings()
        _vector_store = SqliteVectorStore() if settings.is_sqlite else PgVectorStore()
        logger.info(f"[Polystore] VectorStore backend = {_vector_store.backend_name}")
    return _vector_store
