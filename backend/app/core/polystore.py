"""
KAEOS Polystore — lightweight SQLite-backed TF-IDF vector store.

Provides a drop-in `vector_store` singleton that satisfies the interface
expected by knowledge-base modules:

    await vector_store.upsert(collection, doc_id, text, metadata)
    results = await vector_store.search(collection, query, top_k)  # list[{doc_id, text, score, metadata}]

Uses keyword-frequency scoring (TF-IDF approximation) stored in an
async SQLite database via aiosqlite so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import aiosqlite
    _HAS_AIOSQLITE = True
except ImportError:
    _HAS_AIOSQLITE = False
    logger.warning("[polystore] aiosqlite not installed — falling back to in-memory store")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tf(tokens: list[str]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    n = max(len(tokens), 1)
    return {t: c / n for t, c in counts.items()}


class _InMemoryBackend:
    """Fallback when aiosqlite is not installed."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}  # key="{collection}::{doc_id}"

    async def upsert(self, collection: str, doc_id: str, text: str, metadata: dict) -> None:
        key = f"{collection}::{doc_id}"
        tokens = _tokenize(text)
        self._docs[key] = {
            "collection": collection,
            "doc_id": doc_id,
            "text": text,
            "tokens": tokens,
            "tf": _tf(tokens),
            "metadata": metadata,
        }

    async def search(self, collection: str, query: str, top_k: int) -> list[dict]:
        q_terms = set(_tokenize(query))
        candidates = [v for v in self._docs.values() if v["collection"] == collection]
        scored = []
        for doc in candidates:
            score = sum(doc["tf"].get(t, 0.0) for t in q_terms)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"doc_id": d["doc_id"], "text": d["text"], "score": s, "metadata": d["metadata"]} for s, d in scored[:top_k]]


class _SQLiteBackend:
    _DB_PATH = os.environ.get("POLYSTORE_DB", "polystore.db")

    def __init__(self) -> None:
        self._ready = False
        self._lock = asyncio.Lock()

    async def _init(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            async with aiosqlite.connect(self._DB_PATH) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS polystore_docs (
                        collection TEXT NOT NULL,
                        doc_id     TEXT NOT NULL,
                        text       TEXT NOT NULL,
                        tf_json    TEXT NOT NULL,
                        metadata   TEXT NOT NULL DEFAULT '{}',
                        PRIMARY KEY (collection, doc_id)
                    )
                """)
                await db.commit()
            self._ready = True

    async def upsert(self, collection: str, doc_id: str, text: str, metadata: dict) -> None:
        await self._init()
        tokens = _tokenize(text)
        tf = _tf(tokens)
        async with aiosqlite.connect(self._DB_PATH) as db:
            await db.execute("""
                INSERT INTO polystore_docs (collection, doc_id, text, tf_json, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection, doc_id) DO UPDATE SET
                    text=excluded.text, tf_json=excluded.tf_json, metadata=excluded.metadata
            """, (collection, doc_id, text, json.dumps(tf), json.dumps(metadata)))
            await db.commit()

    async def search(self, collection: str, query: str, top_k: int) -> list[dict]:
        await self._init()
        q_terms = set(_tokenize(query))
        async with aiosqlite.connect(self._DB_PATH) as db:
            async with db.execute(
                "SELECT doc_id, text, tf_json, metadata FROM polystore_docs WHERE collection=?",
                (collection,)
            ) as cursor:
                rows = await cursor.fetchall()
        scored = []
        for doc_id, text, tf_json, meta_json in rows:
            tf = json.loads(tf_json)
            score = sum(tf.get(t, 0.0) for t in q_terms)
            if score > 0:
                scored.append((score, doc_id, text, json.loads(meta_json)))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"doc_id": d, "text": t, "score": s, "metadata": m} for s, d, t, m in scored[:top_k]]


class _VectorStore:
    """Public interface: wraps either SQLite or in-memory backend."""

    def __init__(self) -> None:
        self._backend: _SQLiteBackend | _InMemoryBackend = (
            _SQLiteBackend() if _HAS_AIOSQLITE else _InMemoryBackend()
        )

    async def upsert(self, collection: str, doc_id: str, text: str, metadata: dict | None = None) -> None:
        await self._backend.upsert(collection, doc_id, text, metadata or {})
        logger.debug(f"[polystore] upsert collection={collection!r} doc_id={doc_id!r}")

    async def search(self, collection: str, query: str, top_k: int = 5) -> list[dict]:
        results = await self._backend.search(collection, query, top_k)
        logger.debug(f"[polystore] search collection={collection!r} query={query!r} hits={len(results)}")
        return results


vector_store = _VectorStore()


async def polystore_health() -> dict:
    backend_name = "sqlite" if _HAS_AIOSQLITE else "in-memory"
    return {
        "polystore": {
            "backend": backend_name,
            "status": "ok",
            "db_path": _SQLiteBackend._DB_PATH if _HAS_AIOSQLITE else None,
        }
    }
