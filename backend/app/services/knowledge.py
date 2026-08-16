"""
KAEOS L3 Polystore retrieval.

Semantic and lexical retrieval over governed rules and skills:
  * semantic_search: cosine ranking over rule embeddings; returns nothing when
    embeddings are simulated (no pseudo-vector noise dressed as recall).
  * search_skills: RRF hybrid of a real cosine and a lexical rank, with an
    honest per-record retrieval_mode; degrades to lexical-only.
  * embed_skill / backfill_skill_embeddings: maintain the skill semantic index,
    never persisting simulated pseudo-vectors.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class PolystoreEngine:
    """L3 knowledge retrieval over governed rules and skills.

    semantic_search ranks rule embeddings by cosine; search_skills fuses a real
    cosine with a lexical rank (honest per-record retrieval_mode) and degrades to
    lexical-only when no semantic vector is available.
    """

    def __init__(self, llm: Optional[LLMRouter] = None):
        self.llm = llm or LLMRouter()
        # Set by _generate_embedding_for_text: True when the last query embedding
        # was a non-semantic seeded pseudo-vector (no provider reachable).
        self._last_query_simulated: bool = False

    async def semantic_search(
        self,
        query_text: str,
        tenant_id: str,
        top_k: int = 5,
        domain_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Vector similarity search over the rule embeddings.
        Returns top-k rules ranked by cosine similarity to the query.
        Requires pgvector and a real (non-simulated) embedding model.

        When embeddings are simulated (no provider reachable), the query vector is
        a seeded hash with no semantic meaning, so any "match" it produces is noise
        dressed as a cosine score. The rule store has no lexical index to fall back
        to, so we return NOTHING rather than launder pseudo-vector noise as
        semantic recall.
        """
        query_embedding = await self._generate_embedding_for_text(query_text, tenant_id)
        if not query_embedding or self._last_query_simulated:
            return []

        domain_clause = "AND r.domain = :domain" if domain_filter else ""
        params = {
            "tenant_id": tenant_id,
            "embedding": query_embedding,
            "top_k": top_k,
        }
        if domain_filter:
            params["domain"] = domain_filter

        _rule_sim_sql = (
            "SELECT r.id, r.statement, r.domain, r.confidence_scalar, "  # nosec B608
            "1 - (re.embedding <=> :embedding) AS similarity "
            "FROM rule_embeddings re "
            "JOIN rules r ON r.id = re.rule_id "
            f"WHERE re.tenant_id = :tenant_id {domain_clause} "  # domain_clause is a fixed literal; value arrives via :domain bind
            "ORDER BY re.embedding <=> :embedding "
            "LIMIT :top_k"
        )
        async with AsyncSessionLocal() as session:
            rows = await session.execute(text(_rule_sim_sql), params)
            return [
                {
                    "rule_id": row.id,
                    "statement": row.statement,
                    "domain": row.domain,
                    "confidence": row.confidence_scalar,
                    "similarity": float(row.similarity),
                    "retrieval_mode": "semantic",
                }
                for row in rows.fetchall()
            ]

    async def search_skills(
        self,
        query_text: str,
        tenant_id: str,
        top_k: int = 5,
        domain_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Skill retrieval with an HONEST score contract.

        Every returned dict carries ``retrieval_mode``:
          * ``"hybrid"``  — a real cosine (``similarity``) AND a lexical rank were
            fused via Reciprocal Rank Fusion; ``fused_score`` is the ranking key.
          * ``"lexical"`` — no usable semantic vector (simulated embeddings or no
            pgvector); ranked by ``lexical_score`` (BM25-lite, [0,1]).
            ``similarity`` is ``None`` — a keyword hit is NEVER reported as cosine.

        This replaces the old fallback that fabricated ``similarity: 0.85`` for a
        substring match, laundering a keyword coincidence as a high cosine score.
        """
        from app.services.retrieval import lexical_score, reciprocal_rank_fusion

        async def lexical_matches() -> list[dict]:
            from app.models.domain import Skill
            async with AsyncSessionLocal() as session:
                stmt = select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
                if domain_filter:
                    stmt = stmt.where(Skill.domain == domain_filter)
                result = await session.execute(stmt)
                skills = result.scalars().all()
            matched = []
            for skill in skills:
                score = lexical_score(query_text, _skill_search_text(skill))
                if score > 0:
                    matched.append({
                        "skill_id": skill.skill_id,
                        "skill_db_id": skill.id,
                        "domain": skill.domain,
                        "lexical_score": score,
                    })
            matched.sort(key=lambda x: x["lexical_score"], reverse=True)
            return matched

        query_embedding = await self._generate_embedding_for_text(query_text, tenant_id)
        lexical = await lexical_matches()

        # No usable semantic vector -> honest lexical-only results.
        if not query_embedding or self._last_query_simulated:
            for m in lexical:
                m["similarity"] = None
                m["retrieval_mode"] = "lexical"
            return lexical[:top_k]

        domain_clause = "AND s.domain = :domain" if domain_filter else ""
        params = {"tenant_id": tenant_id, "embedding": query_embedding, "top_k": max(top_k * 4, 20)}
        if domain_filter:
            params["domain"] = domain_filter

        _skill_sim_sql = (
            "SELECT s.skill_id, s.id as skill_db_id, s.domain, "  # nosec B608
            "1 - (se.embedding <=> :embedding) AS similarity "
            "FROM skill_embeddings se "
            "JOIN skills s ON s.id = se.skill_db_id "
            f"WHERE se.tenant_id = :tenant_id AND s.status = 'ACTIVE' {domain_clause} "  # domain_clause is a fixed literal; value arrives via :domain bind
            "ORDER BY se.embedding <=> :embedding LIMIT :top_k"
        )
        try:
            async with AsyncSessionLocal() as session:
                rows = await session.execute(text(_skill_sim_sql), params)
                vector_hits = [
                    {"skill_id": r.skill_id, "skill_db_id": r.skill_db_id,
                     "domain": r.domain, "similarity": float(r.similarity)}
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"Vector search failed (likely sqlite), falling back to lexical: {e}")
            for m in lexical:
                m["similarity"] = None
                m["retrieval_mode"] = "lexical"
            return lexical[:top_k]

        # Vector store had nothing to say: RRF over a single (lexical) list is
        # just the lexical ranking - label it honestly instead of "hybrid".
        if not vector_hits:
            for m in lexical:
                m["similarity"] = None
                m["retrieval_mode"] = "lexical"
            return lexical[:top_k]

        # Hybrid: fuse the two rankings by RRF over skill_db_id.
        by_id: dict[str, dict] = {}
        for h in vector_hits:
            by_id[h["skill_db_id"]] = {**h, "lexical_score": 0.0}
        for m in lexical:
            if m["skill_db_id"] in by_id:
                by_id[m["skill_db_id"]]["lexical_score"] = m["lexical_score"]
            else:
                by_id[m["skill_db_id"]] = {**m, "similarity": None}
        fused = reciprocal_rank_fusion([
            [h["skill_db_id"] for h in vector_hits],
            [m["skill_db_id"] for m in lexical],
        ])
        out = []
        for sid, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True):
            rec = by_id[sid]
            rec["fused_score"] = round(score, 6)
            # A lexical-only record (no vector hit) has similarity=None; only a
            # record with a real cosine is genuinely hybrid. Label per record.
            rec["retrieval_mode"] = "hybrid" if rec.get("similarity") is not None else "lexical"
            out.append(rec)
        return out[:top_k]

    # Single attempt on this user-facing query path: a down provider must fail
    # fast to the honest empty-result path, not stall the request behind retries.
    # (The inner try/except already returns None on any error rather than raising.)
    async def _generate_embedding_for_text(self, text_: str,
                                            tenant_id: Optional[str] = None) -> Optional[list]:
        """Embed a plain text string (used for semantic_search queries).

        Sets ``self._last_query_simulated`` from the router provenance so callers
        can tell a real cosine-capable vector from a seeded pseudo-vector.

        The query is embedded with the SAME tenant router the stored vectors were
        written with (so a BYOK tenant whose embedding model differs from the
        platform default produces a comparable query vector); pass tenant_id from
        the caller rather than relying on the ambient contextvar, which a
        background job may not have set."""
        self._last_query_simulated = False
        try:
            from app.services.llm_router import get_tenant_router
            router = await get_tenant_router(tenant_id)
            vectors = await router.embed([text_])
            self._last_query_simulated = bool(router.embeddings_simulated)
            return vectors[0] if vectors else None
        except Exception as exc:
            logger.warning(f"[Polystore] Query embedding failed: {exc}")
            return None


# ── Skill semantic index (module-level: shared by every skill write path) ────


def _skill_search_text(skill) -> str:
    """The searchable text of a skill: its id/name + all trigger patterns.

    One definition shared by the lexical matcher and the embedding writer so
    both retrieval lanes always index the same surface.
    """
    parts = [str(skill.skill_id or "")]
    for t in (skill.triggers or []):
        if isinstance(t, dict) and "pattern" in t:
            parts.append(str(t["pattern"]))
        elif isinstance(t, str):
            parts.append(t)
    return " ".join(parts)


async def embed_skill(skill, tenant_id: str, router=None) -> bool:
    """Upsert the semantic embedding for one skill into ``skill_embeddings``.

    Non-blocking by contract: a failed embed must NEVER fail the skill write,
    so every failure is logged and swallowed. Returns True only when a REAL
    vector was persisted. Simulated embeddings are never persisted - the same
    guard as rules: a stored pseudo-vector would later match a real query and
    fabricate a 'semantic' similarity that was never a true cosine.
    """
    try:
        if router is None:
            from app.services.llm_router import get_tenant_router
            router = await get_tenant_router(tenant_id)
        vectors = await router.embed([_skill_search_text(skill)])
        if getattr(router, "embeddings_simulated", False):
            logger.info("[Polystore] embeddings simulated - not persisting a "
                        "pseudo-vector for skill %s", skill.id)
            return False
        if not vectors:
            return False
        from app.models.domain import SkillEmbedding
        async with AsyncSessionLocal() as session:
            await session.merge(SkillEmbedding(
                skill_db_id=skill.id,
                tenant_id=tenant_id,
                embedding=vectors[0],
                updated_at=datetime.now(timezone.utc),
            ))
            await session.commit()
        return True
    except Exception as exc:
        logger.warning("[Polystore] Skill embedding failed (non-fatal) for %s: %s",
                       getattr(skill, "id", None), exc)
        return False


async def backfill_skill_embeddings(db: AsyncSession, tenant_id: str) -> dict:
    """Embed ACTIVE skills that have no embedding row yet. Idempotent.

    Runs under THIS tenant's router (BYOK / data-residency respected). When
    that router can only produce simulated embeddings nothing is persisted and
    the result says so - honesty over a fabricated 'backfilled' count.
    """
    from app.models.domain import Skill, SkillEmbedding
    from app.services.llm_router import get_tenant_router

    have = select(SkillEmbedding.skill_db_id).where(
        SkillEmbedding.tenant_id == tenant_id
    )
    rows = await db.execute(
        select(Skill).where(
            Skill.tenant_id == tenant_id,
            Skill.status == "ACTIVE",
            Skill.id.notin_(have),
        )
    )
    missing = rows.scalars().all()

    router = await get_tenant_router(tenant_id)
    embedded = 0
    simulated = False
    # ponytail: sequential embeds (one call per skill); batch router.embed(texts)
    # in one call if backfill latency ever matters at catalog scale.
    for skill in missing:
        if await embed_skill(skill, tenant_id, router=router):
            embedded += 1
        elif getattr(router, "embeddings_simulated", False):
            # Every remaining call would also produce a pseudo-vector - stop.
            simulated = True
            break
    return {
        "tenant_id": tenant_id,
        "missing": len(missing),
        "embedded": embedded,
        "embeddings_simulated": simulated,
    }
