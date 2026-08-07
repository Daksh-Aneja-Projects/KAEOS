import asyncio
import logging

from app.core.tenant import get_tenant_id, require_role
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.result_cache import get_or_compute
from app.models.domain import Signal, Rule
from app.services.extraction import ContradictionDetector, RuleMiner
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extraction", tags=["Extraction — L2 Knowledge Extraction"])

# How many rule-mining calls may be in flight at once.
#
# Measured against the local 7B on this box, seven prompts of ~25 signals each:
# sequential 59.4s, 2 at a time 31.9s, 3 at a time 22.4s, all 7 at once 24.5s.
# Past three the GPU thrashes and it gets slower, so an unbounded fan-out is not
# just impolite, it is worse. The bound also matters because the same model
# serves the governance gates and the copilot: one endpoint must not be able to
# queue every other request behind it.
# ponytail: a per-endpoint bound, not a global one. If more endpoints start
# fanning out, this belongs in the LLM router as a shared limiter.
_MINING_CONCURRENCY = 3

class CandidateRule(BaseModel):
    statement: str
    trigger_json: dict
    action_json: dict
    domain: str
    confidence_basis: str

@router.get("/candidates")
async def get_candidate_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Group signals by domain — THIS tenant's signals only: mined rules carry
    # clean_payload content, so an unfiltered read here leaks another
    # customer's data into this tenant's rule candidates.
    # Newest-first cap: Signal is the raw ingest firehose (every connector poll
    # and webhook writes one). Unbounded, the whole table was materialized AND
    # each domain's cluster became an LLM prompt, so the prompt grew until the
    # context window rejected it.
    signals = await db.execute(
        select(Signal)
        .where(Signal.tenant_id == tenant_id)
        .order_by(Signal.created_at.desc())
        .limit(500)
    )
    signal_list = signals.scalars().all()
    
    miner = RuleMiner()
    clusters: dict[str, list] = {}
    for s in signal_list:
        if s.domain:
            clusters.setdefault(s.domain, []).append(s)

    # One LLM call per domain, run concurrently. They were sequential, so the
    # request cost the SUM of seven local-model calls. Nothing here shares the
    # request's AsyncSession (the DB read is already done and the miner only
    # talks to the model), so gather is safe; the same is NOT true of the
    # db.execute fan-outs elsewhere in this codebase.
    minable = [(dom, cluster) for dom, cluster in sorted(clusters.items()) if len(cluster) >= 3]

    async def _mine_all() -> list[dict]:
        sem = asyncio.Semaphore(_MINING_CONCURRENCY)

        async def _mine(cluster) -> dict | None:
            async with sem:
                return await miner.extract_rule([{"clean_payload": s.clean_payload} for s in cluster])

        results = await asyncio.gather(
            *(_mine(cluster) for _dom, cluster in minable),
            return_exceptions=True,
        )
        out: list[dict] = []
        for (dom, _cluster), rule_dict in zip(minable, results):
            if isinstance(rule_dict, Exception):
                logger.warning("Rule mining failed for domain %s: %s", dom, rule_dict)
                continue
            if rule_dict:
                rule_dict["domain"] = dom
                rule_dict["id"] = f"cand_{dom}_{len(out)}"
                out.append(rule_dict)
        return out

    # Cached against the signals actually mined. The fingerprint is every
    # signal id that reaches a prompt, so ingesting a new signal changes it and
    # the rules are re-mined; nothing else can make this answer go stale. Only
    # the ids are hashed, never payload content.
    parts = [[dom, sorted(s.id for s in cluster[: miner.MAX_PROMPT_SIGNALS])] for dom, cluster in minable]
    candidates, _cached = await get_or_compute(
        "extraction_candidates",
        tenant_id,
        parts,
        _mine_all,
        should_cache=lambda v: bool(v),   # a total mining failure retries next time
    )

    return {"candidates": candidates}

@router.post("/detect-conflict", dependencies=[Depends(require_role("operator"))])
async def detect_conflict(candidate: CandidateRule, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    detector = ContradictionDetector()
    existing_rules = await db.execute(
        select(Rule).where(Rule.tenant_id == tenant_id, Rule.domain == candidate.domain)
    )
    kb_list = [{"id": r.id, "domain": r.domain, "trigger_json": r.trigger_json, "action_json": r.action_json} for r in existing_rules.scalars().all()]
    
    result = await detector.detect(candidate.model_dump(), kb_list)
    return result


@router.get("/signals")
async def get_signals(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """All raw signals ordered by recency, explicitly serialized."""
    result = await db.execute(
        select(Signal)
        .where(Signal.tenant_id == tenant_id)
        .order_by(Signal.created_at.desc())
        .limit(100)
    )
    signals = result.scalars().all()
    return {
        "total": len(signals),
        "signals": [
            {
                "id": s.id,
                "source_type": s.source_type,
                "source_entity": s.source_entity,
                "signal_type": s.signal_type,
                "domain": s.domain,
                "clean_payload": s.clean_payload,
                "authority_score": s.authority_score,
                "novelty_score": s.novelty_score,
                "pii_present": s.pii_present,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signals
        ],
    }
