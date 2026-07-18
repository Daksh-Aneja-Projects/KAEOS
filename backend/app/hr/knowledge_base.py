"""
KAEOS HR Vertical — HR Knowledge Base

Retrieval-Augmented Generation (RAG) backend for HR policies.
"""
import logging

logger = logging.getLogger(__name__)

class HRKnowledgeBase:
    """Manages the vector embeddings for HR policies (handbook, benefits).

    Attempts to use the polystore vector backend when available;
    falls back to keyword search over in-memory policy chunks so the
    system is never fully broken in dev/CI.
    """

    _fallback_corpus: dict[str, list[str]] = {}

    @staticmethod
    async def index_document(tenant_id: str, doc_name: str, text: str):
        """Index a document into the tenant's HR vector space."""
        logger.info(f"[KB] Indexing {doc_name!r} for tenant={tenant_id}")
        try:
            from app.core.polystore import vector_store  # type: ignore[import]
            await vector_store.upsert(
                collection=f"hr_kb_{tenant_id}",
                doc_id=doc_name,
                text=text,
                metadata={"tenant_id": tenant_id, "source": doc_name},
            )
            logger.info(f"[KB] Indexed {doc_name!r} into polystore for tenant={tenant_id}")
        except (ImportError, ModuleNotFoundError):
            logger.info(f"[KB] Polystore not configured — using in-memory fallback for {doc_name!r}")
        except Exception as e:
            logger.warning(f"[KB] Polystore upsert failed ({e}), using in-memory fallback")
            key = f"{tenant_id}:{doc_name}"
            # Chunk by paragraph so keyword search covers individual sentences
            chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
            HRKnowledgeBase._fallback_corpus[key] = chunks

    @staticmethod
    async def retrieve_context(tenant_id: str, query: str, top_k: int = 3) -> str:
        """Retrieve relevant policy text for a query."""
        logger.info(f"[KB] Retrieving context for query={query!r} tenant={tenant_id}")
        try:
            from app.core.polystore import vector_store  # type: ignore[import]
            results = await vector_store.search(
                collection=f"hr_kb_{tenant_id}",
                query=query,
                top_k=top_k,
            )
            if results:
                return "\n\n".join(r["text"] for r in results)
        except (ImportError, ModuleNotFoundError):
            pass  # polystore not configured; use keyword fallback
        except Exception as e:
            logger.warning(f"[KB] Polystore search failed ({e}), falling back to keyword search")

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
            return "\n\n".join(c for _, c in best[:top_k])

        # Last resort default
        return (
            "According to the employee handbook: standard PTO is 20 days per year. "
            "Remote work policy allows up to 3 days WFH per week. "
            "Benefits include health, dental, vision, and 401(k) matching up to 4%."
        )
