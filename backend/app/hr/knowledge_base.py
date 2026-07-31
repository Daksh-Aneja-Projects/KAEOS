"""
KAEOS HR Vertical — HR Knowledge Base

Retrieval-Augmented Generation (RAG) backend for HR policies.
"""
import logging

from app.services import prompt_guard

logger = logging.getLogger(__name__)


def _fence(text: str) -> str:
    """Fence retrieved policy text as untrusted data before it enters a prompt.

    Indexed documents are tenant-uploaded content, so a poisoned handbook could
    otherwise smuggle instructions into every agent that retrieves it.
    """
    return prompt_guard.wrap_untrusted(text) if text else ""


class HRKnowledgeBase:
    """Manages the vector embeddings for HR policies (handbook, benefits).

    Attempts to use the polystore vector backend when available;
    falls back to keyword search over in-memory policy chunks so the
    system is never fully broken in dev/CI.
    """

    _fallback_corpus: dict[str, list[str]] = {}

    @staticmethod
    async def index_document(tenant_id: str, doc_name: str, text: str):
        """Index a document into the tenant's HR vector space.

        Uses the REAL polystore VectorStore (get_vector_store()), which is
        tenant-isolated at the storage layer (tenant_id column + Postgres RLS).
        The previous code imported the shadowed standalone `vector_store`
        instance, which never resolved, so this path silently fell back to
        keyword search on every call.
        """
        logger.info(f"[KB] Indexing {doc_name!r} for tenant={tenant_id}")
        # Chunk by paragraph so retrieval works at sentence/section granularity.
        chunks = [c.strip() for c in text.split("\n\n") if c.strip()] or [text.strip()]
        try:
            from app.core.polystore import get_vector_store
            from app.services.llm_router import get_tenant_router
            store = get_vector_store()
            router = await get_tenant_router(tenant_id)
            for i, chunk in enumerate(chunks):
                embedding = (await router.embed([chunk]))[0]
                await store.upsert(
                    vector_id=f"{doc_name}#{i}",
                    tenant_id=tenant_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"source": doc_name, **router.embedding_metadata()},
                    namespace="hr_kb",
                )
            logger.info(f"[KB] Indexed {len(chunks)} chunk(s) of {doc_name!r} for tenant={tenant_id}")
            return
        except Exception as e:
            logger.warning(f"[KB] Vector index failed ({e}); using keyword fallback for {doc_name!r}")
        # Keyword fallback — tenant-prefixed key keeps corpora isolated.
        HRKnowledgeBase._fallback_corpus[f"{tenant_id}:{doc_name}"] = chunks

    @staticmethod
    async def retrieve_context(tenant_id: str, query: str, top_k: int = 3) -> str:
        """Retrieve relevant policy text for a query."""
        logger.info(f"[KB] Retrieving context for query={query!r} tenant={tenant_id}")
        try:
            from app.core.polystore import get_vector_store
            from app.services.llm_router import get_tenant_router
            store = get_vector_store()
            router = await get_tenant_router(tenant_id)
            query_embedding = (await router.embed([query]))[0]
            results = await store.search(
                tenant_id=tenant_id,
                query_embedding=query_embedding,
                limit=top_k,
                namespace="hr_kb",
            )
            if results:
                return _fence("\n\n".join(
                    r.get("content", "") for r in results if r.get("content")))
        except Exception as e:
            logger.warning(f"[KB] Vector search failed ({e}), falling back to keyword search")

        # Keyword fallback: score chunks by term overlap
        query_terms = set(query.lower().split())
        best: list[tuple[int, str]] = []
        for key, chunks in HRKnowledgeBase._fallback_corpus.items():
            if not key.startswith(f"{tenant_id}:"):
                continue
            for chunk in chunks:
                score = sum(1 for t in query_terms if t in chunk.lower())
                if score > 0:
                    best.append((score, chunk))

        best.sort(key=lambda x: x[0], reverse=True)
        if best:
            return _fence("\n\n".join(c for _, c in best[:top_k]))

        # Total miss (nothing indexed, or nothing matched). Return NOTHING. This
        # used to return an invented employee handbook (PTO days, 401k match)
        # that no tenant had ever uploaded, so every agent downstream quoted
        # fabricated policy as fact. An empty context lets the agent say it has
        # no policy data, which is the truth.
        logger.info(f"[KB] No policy context found for query={query!r} tenant={tenant_id}")
        return ""
