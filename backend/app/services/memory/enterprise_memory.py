"""
KAEOS Enterprise Memory Service

Stores and recalls organizational memory (decisions, contexts, outcomes) as real
semantic vectors. Embeddings come from ``LLMRouter.embed`` and are persisted /
searched through the polystore :class:`VectorStore` abstraction, so the same code
runs on pgvector (Postgres) and in-process cosine (SQLite dev stack).

Replaces the previous stub that inserted ``[0.0]*1536`` mock vectors via raw
pgvector SQL against a table that never existed.
"""

import logging
import uuid
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.polystore import get_vector_store
from app.services.llm_router import get_tenant_router
from app.services.llm_support import configured_embedding_model

logger = logging.getLogger(__name__)

_MEMORY_NAMESPACE = "enterprise_memory"


class EnterpriseMemoryService:
    """Semantic organizational memory backed by the polystore VectorStore."""

    @staticmethod
    async def _embed(text_value: str, tenant_id: Optional[str] = None) -> tuple[List[float], dict]:
        """Embed on the tenant's model (BYOK) and return ``(vector, provenance)``.

        ``provenance`` carries the embedding model name + a simulated flag to stamp
        onto the upserted vector, so a later pass can detect vectors that must be
        re-embedded (model changed) or excluded (non-semantic pseudo-vectors).
        """
        router = await get_tenant_router(tenant_id)
        # Embed on the SAME model that sizes the pgvector column width
        # (configured_embedding_model), so a changed EMBEDDING_MODEL never
        # dim-mismatches the store. See the matching fix in llm_router.embed.
        vectors = await router.embed([text_value], model=configured_embedding_model())
        return (vectors[0] if vectors else []), router.embedding_metadata()

    @staticmethod
    async def store_decision_memory(
        db: Optional[AsyncSession],
        tenant_id: str,
        context: str,
        decision: dict,
        outcome: str = "UNKNOWN",
    ) -> str:
        """Embed and store a decision + its context. Returns the memory id.

        ``db`` is accepted for backward compatibility but the VectorStore manages
        its own sessions.
        """
        memory_id = str(uuid.uuid4())
        content = f"Context: {context}. Decision: {decision}. Outcome: {outcome}"
        try:
            embedding, emeta = await EnterpriseMemoryService._embed(content, tenant_id)
            store = get_vector_store()
            await store.upsert(
                vector_id=memory_id,
                tenant_id=tenant_id,
                content=content,
                embedding=embedding,
                metadata={"memory_type": "DECISION", "decision": decision, "outcome": outcome, **emeta},
                namespace=_MEMORY_NAMESPACE,
            )
            logger.info(f"[Memory] Stored decision memory {memory_id} for {tenant_id}")
        except Exception as e:
            logger.error(f"[Memory] Failed to store decision memory: {e}")
        return memory_id

    @staticmethod
    async def recall_similar_situations(
        db: Optional[AsyncSession],
        tenant_id: str,
        current_context: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Cosine semantic search over stored memories for the current context.

        Returns [] when embeddings are simulated: a seeded pseudo-vector recalls
        random memories with a plausible-looking cosine, so we surface no recall
        rather than fabricate 'similar situations' that are noise.
        """
        try:
            embedding, prov = await EnterpriseMemoryService._embed(current_context, tenant_id)
            if prov.get("simulated"):
                logger.info("[Memory] embeddings simulated; no semantic recall for %s", tenant_id)
                return []
            store = get_vector_store()
            results = await store.search(
                tenant_id=tenant_id,
                query_embedding=embedding,
                limit=limit,
                namespace=_MEMORY_NAMESPACE,
            )
            return [
                {
                    "id": r["id"],
                    "memory_type": (r.get("metadata") or {}).get("memory_type", "DECISION"),
                    "content": r["content"],
                    "metadata": r.get("metadata", {}),
                    "similarity": r["similarity"],
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"[Memory] Failed to recall memory: {e}")
            return []

    @staticmethod
    async def store_outcome(db: Optional[AsyncSession], memory_id: str, actual_outcome: str) -> None:
        """Patch a stored memory with its realized outcome so the system can learn."""
        try:
            store = get_vector_store()
            await store.update_metadata(memory_id, "outcome", actual_outcome)
            logger.info(f"[Memory] Updated outcome for memory {memory_id}: {actual_outcome}")
        except Exception as e:
            logger.error(f"[Memory] Failed to update memory outcome: {e}")
