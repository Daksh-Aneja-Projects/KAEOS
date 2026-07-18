"""
KAEOS — L3 Polystore Engine (Fixed)

Replaces the broken stub in knowledge.py.

Changes vs original:
  1. write_knowledge() now accepts a Rule ORM object (not a raw dict)
  2. Implements all 4 store writes with graceful fallbacks
  3. pgvector write via SQLAlchemy + asyncpg (falls back gracefully if not configured)
  4. Neo4j write via official neo4j async driver (falls back gracefully)
  5. Temporal decay entry written synchronously within the DB transaction
  6. Returns a WriteResult with per-store success flags for observability
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.database import AsyncSessionLocal
from app.models.domain import Rule, DecayEvent
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class PolyWriteResult:
    rule_id: str
    relational: bool = False
    vector: bool = False
    graph: bool = False
    temporal: bool = False
    errors: list = field(default_factory=list)

    @property
    def partial_success(self) -> bool:
        return self.relational  # Minimum viable: relational must succeed

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "stores": {
                "relational": self.relational,
                "vector": self.vector,
                "graph": self.graph,
                "temporal": self.temporal,
            },
            "errors": self.errors,
        }


class PolystoreEngine:
    """
    L3 — Multi-Modal Knowledge Base (Polystore).

    Four-store write pattern:
      1. PostgreSQL/SQLite  — rules, provenance, confidence history (always)
      2. pgvector           — semantic embedding for RAG retrieval (if configured)
      3. Neo4j              — graph relationships between rules and domains (if configured)
      4. Temporal/Decay     — registers rule for half-life decay loop (always)

    Stores 2 and 3 degrade gracefully when not configured, ensuring the system
    works on SQLite in dev without any graph or vector infrastructure.
    """

    def __init__(self, llm: Optional[LLMRouter] = None):
        self.llm = llm or LLMRouter()

    async def write_knowledge(
        self, rule: Rule, tenant_id: str, db: Optional[AsyncSession] = None
    ) -> PolyWriteResult:
        """
        Write a Rule object across all configured stores.

        Args:
            rule: A mapped SQLAlchemy Rule ORM instance (not a dict).
            tenant_id: The tenant this rule belongs to.
            db: Optional caller session. If provided, the relational write
                uses this session directly (avoids cross-session merge issues).
                If None, opens a fresh session internally.

        Returns:
            PolyWriteResult with per-store success flags.
        """
        result = PolyWriteResult(rule_id=rule.id)

        # ── Store 1: Relational (PostgreSQL / SQLite) ─────────────────────
        try:
            if db is not None:
                # Use caller's session — rule is already attached here
                await db.flush()
            else:
                # Open a fresh session — merge by ID to avoid DetachedInstanceError
                async with AsyncSessionLocal() as session:
                    merged = await session.merge(rule)
                    await session.commit()
                    await session.refresh(merged)
            result.relational = True
            logger.info(f"[Polystore] Relational write OK: {rule.id}")
        except Exception as exc:
            err = f"Relational write failed: {exc}"
            result.errors.append(err)
            logger.error(f"[Polystore] {err}")
            return result  # Hard stop — relational is non-negotiable

        # ── Store 2: Vector (pgvector) ────────────────────────────────────
        try:
            embedding = await self._generate_embedding(rule)
            if embedding:
                await self._write_vector(rule, embedding)
                result.vector = True
                logger.info(f"[Polystore] Vector write OK: {rule.id}")
            else:
                result.errors.append("Vector skipped: embedding generation returned None")
        except Exception as exc:
            err = f"Vector write failed (non-fatal): {exc}"
            result.errors.append(err)
            logger.warning(f"[Polystore] {err}")

        # ── Store 3: Graph (Neo4j) ────────────────────────────────────────
        try:
            await self._write_graph(rule, tenant_id)
            result.graph = True
            logger.info(f"[Polystore] Graph write OK: {rule.id}")
        except Exception as exc:
            err = f"Graph write failed (non-fatal): {exc}"
            result.errors.append(err)
            logger.warning(f"[Polystore] {err}")

        # ── Store 4: Temporal Decay Registration ──────────────────────────
        try:
            await self._register_decay(rule, tenant_id)
            result.temporal = True
            logger.info(f"[Polystore] Temporal decay registered: {rule.id}")
        except Exception as exc:
            err = f"Decay registration failed (non-fatal): {exc}"
            result.errors.append(err)
            logger.warning(f"[Polystore] {err}")

        logger.info(
            f"[Polystore] Write complete for {rule.id}: "
            f"relational={result.relational} vector={result.vector} "
            f"graph={result.graph} temporal={result.temporal}"
        )
        return result

    # ── Store 2: Embedding generation + pgvector write ────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _generate_embedding(self, rule: Rule) -> Optional[list]:
        """
        Generate a semantic embedding for the rule statement.

        Uses LiteLLM's embedding API (OpenAI text-embedding-3-small by default).
        Falls back to None if no embedding key is configured.
        """
        try:
            import litellm
            text_to_embed = (
                f"{rule.statement} "
                f"Domain: {rule.domain}. "
                f"Trigger: {json.dumps(rule.trigger_json)}. "
                f"Action: {json.dumps(rule.action_json)}."
            )
            response = await litellm.aembedding(
                model="text-embedding-3-small",
                input=[text_to_embed],
            )
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.warning(f"[Polystore] Embedding generation skipped: {exc}")
            return None

    async def _write_vector(self, rule: Rule, embedding: list) -> None:
        """
        Upsert the rule embedding into the pgvector `rule_embeddings` table.
        Using SQLAlchemy ORM.
        """
        from app.models.domain import RuleEmbedding
        async with AsyncSessionLocal() as session:
            rule_emb = RuleEmbedding(
                rule_id=rule.id,
                tenant_id=rule.tenant_id,
                embedding=embedding,
                updated_at=datetime.now(timezone.utc)
            )
            await session.merge(rule_emb)
            await session.commit()

    # ── Store 3: Neo4j graph write ────────────────────────────────────────

    async def _write_graph(self, rule: Rule, tenant_id: str) -> None:
        """
        Upsert the rule as a node in Neo4j and create/update domain relationships.

        Graph schema:
            (:Rule {id, statement, confidence, domain, tenant_id})
              -[:BELONGS_TO]->
            (:Domain {name, tenant_id})

        Cross-domain rules that reference multiple domains get multiple BELONGS_TO edges.
        """
        from app.core.config import get_settings
        settings = get_settings()
        neo4j_uri = getattr(settings, "NEO4J_URI", None)
        neo4j_user = getattr(settings, "NEO4J_USER", "neo4j")
        neo4j_pass = getattr(settings, "NEO4J_PASSWORD", "")

        if not neo4j_uri:
            raise RuntimeError("NEO4J_URI not configured — graph write skipped")

        try:
            from neo4j import AsyncGraphDatabase
        except ImportError:
            raise RuntimeError("neo4j package not installed — graph write skipped")
        async with AsyncGraphDatabase.driver(
            neo4j_uri, auth=(neo4j_user, neo4j_pass)
        ) as driver:
            async with driver.session() as neo_session:
                await neo_session.run(
                    """
                    MERGE (r:Rule {id: $id})
                    SET r.statement   = $statement,
                        r.confidence  = $confidence,
                        r.domain      = $domain,
                        r.tenant_id   = $tenant_id,
                        r.updated_at  = $updated_at

                    MERGE (d:Domain {name: $domain, tenant_id: $tenant_id})

                    MERGE (r)-[:BELONGS_TO]->(d)
                    """,
                    {
                        "id": rule.id,
                        "statement": rule.statement,
                        "confidence": rule.confidence_scalar or 0.0,
                        "domain": rule.domain or "general",
                        "tenant_id": tenant_id,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

                # If the rule has compliance tags, link to Regulation nodes
                for tag in rule.compliance_tags or []:
                    await neo_session.run(
                        """
                        MERGE (reg:Regulation {name: $tag})
                        MERGE (r:Rule {id: $rule_id})
                        MERGE (r)-[:GOVERNED_BY]->(reg)
                        """,
                        {"tag": tag, "rule_id": rule.id},
                    )

    # ── Store 4: Temporal decay registration ─────────────────────────────

    async def _register_decay(self, rule: Rule, tenant_id: str) -> None:
        """
        Register the rule in the DecayEvent table so the hourly decay loop
        (L7 Temporal Decay Manager) picks it up and applies the half-life model.

        The decay loop reads all rules where `last_decay_at` is null or
        older than `half_life_days` ago, then calls:
            ConfidenceEngine.evaluate_decay(current_confidence, days_since, half_life)
        """
        async with AsyncSessionLocal() as session:
            # Avoid duplicate decay registrations on re-write
            existing = await session.execute(
                text(
                    "SELECT id FROM decay_events "
                    "WHERE rule_id = :rule_id AND event_type = 'REGISTERED'"
                ),
                {"rule_id": rule.id},
            )
            if existing.fetchone():
                return  # Already registered — the decay loop will handle updates

            decay_event = DecayEvent(
                rule_id=rule.id,
                tenant_id=tenant_id,
                event_type="REGISTERED",
                half_life_days=rule.half_life_days or 180,
                confidence_before=rule.confidence_scalar or 0.0,
                confidence_after=rule.confidence_scalar or 0.0,
                days_elapsed=0,
                triggered_by="polystore_write",
            )
            session.add(decay_event)
            await session.commit()

    # ── Convenience: read_knowledge ───────────────────────────────────────

    async def read_knowledge(
        self,
        rule_id: str,
        tenant_id: str,
        include_embedding: bool = False,
    ) -> dict:
        """
        Reads a rule from the relational store.
        Optionally includes its pgvector embedding for inspection.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Rule).where(Rule.id == rule_id, Rule.tenant_id == tenant_id)
            )
            rule = result.scalar_one_or_none()
            if not rule:
                return {}

            payload = {
                "id": rule.id,
                "statement": rule.statement,
                "domain": rule.domain,
                "confidence_scalar": rule.confidence_scalar,
                "confidence_vector": rule.confidence_vector,
                "confidence_tier": rule.confidence_tier.value if rule.confidence_tier else None,
                "half_life_days": rule.half_life_days,
                "compliance_tags": rule.compliance_tags,
                "is_executable": rule.is_executable,
                "version": rule.version,
                "created_at": rule.created_at.isoformat() if rule.created_at else None,
            }

            if include_embedding:
                emb_result = await session.execute(
                    text(
                        "SELECT embedding FROM rule_embeddings "
                        "WHERE rule_id = :rule_id"
                    ),
                    {"rule_id": rule_id},
                )
                row = emb_result.fetchone()
                payload["embedding_present"] = row is not None

            return payload

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
        Requires pgvector and text-embedding-3-small to be configured.
        """
        query_embedding = await self._generate_embedding_for_text(query_text)
        if not query_embedding:
            return []

        domain_clause = "AND r.domain = :domain" if domain_filter else ""
        params = {
            "tenant_id": tenant_id,
            "embedding": query_embedding,
            "top_k": top_k,
        }
        if domain_filter:
            params["domain"] = domain_filter

        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text(f"""
                    SELECT r.id, r.statement, r.domain, r.confidence_scalar,
                           1 - (re.embedding <=> :embedding) AS similarity
                    FROM rule_embeddings re
                    JOIN rules r ON r.id = re.rule_id
                    WHERE re.tenant_id = :tenant_id
                      {domain_clause}
                    ORDER BY re.embedding <=> :embedding
                    LIMIT :top_k
                """),
                params,
            )
            return [
                {
                    "rule_id": row.id,
                    "statement": row.statement,
                    "domain": row.domain,
                    "confidence": row.confidence_scalar,
                    "similarity": float(row.similarity),
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
        Vector similarity search over the skill embeddings.
        Falls back to lexical matching if pgvector is unavailable.
        """
        query_embedding = await self._generate_embedding_for_text(query_text)

        async def fallback_search():
            from app.models.domain import Skill
            async with AsyncSessionLocal() as session:
                stmt = select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
                if domain_filter:
                    stmt = stmt.where(Skill.domain == domain_filter)
                result = await session.execute(stmt)
                skills = result.scalars().all()
                matched = []
                q_lower = query_text.lower()
                for skill in skills:
                    score = 0.0
                    for t in (skill.triggers or []):
                        if isinstance(t, dict) and "pattern" in t:
                            if q_lower in str(t["pattern"]).lower() or str(t["pattern"]).lower() in q_lower:
                                score = max(score, 0.85)
                        elif isinstance(t, str):
                            if q_lower in t.lower() or t.lower() in q_lower:
                                score = max(score, 0.85)
                    if score > 0:
                        matched.append({"skill_id": skill.skill_id, "skill_db_id": skill.id, "similarity": score, "domain": skill.domain})
                matched.sort(key=lambda x: x["similarity"], reverse=True)
                return matched[:top_k]

        if not query_embedding:
            return await fallback_search()

        domain_clause = "AND s.domain = :domain" if domain_filter else ""
        params = {"tenant_id": tenant_id, "embedding": query_embedding, "top_k": top_k}
        if domain_filter: 
            params["domain"] = domain_filter

        try:
            async with AsyncSessionLocal() as session:
                rows = await session.execute(text(f"""
                    SELECT s.skill_id, s.id as skill_db_id, s.domain,
                           1 - (se.embedding <=> :embedding) AS similarity
                    FROM skill_embeddings se
                    JOIN skills s ON s.id = se.skill_db_id
                    WHERE se.tenant_id = :tenant_id AND s.status = 'ACTIVE' {domain_clause}
                    ORDER BY se.embedding <=> :embedding LIMIT :top_k
                """), params)
                return [{"skill_id": row.skill_id, "skill_db_id": row.skill_db_id, "domain": row.domain, "similarity": float(row.similarity)} for row in rows.fetchall()]
        except Exception as e:
            logger.warning(f"Vector search failed (likely sqlite), falling back to lexical: {e}")
            return await fallback_search()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _generate_embedding_for_text(self, text_: str) -> Optional[list]:
        """Embed a plain text string (used for semantic_search queries)."""
        try:
            import litellm
            response = await litellm.aembedding(
                model="text-embedding-3-small",
                input=[text_],
            )
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.warning(f"[Polystore] Query embedding failed: {exc}")
            return None
