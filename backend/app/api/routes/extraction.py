from app.core.tenant import get_tenant_id, require_role
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.domain import Signal, Rule
from app.services.extraction import ContradictionDetector, RuleMiner
from pydantic import BaseModel

router = APIRouter(prefix="/extraction", tags=["Extraction — L2 Knowledge Extraction"])

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
    signals = await db.execute(select(Signal).where(Signal.tenant_id == tenant_id))
    signal_list = signals.scalars().all()
    
    miner = RuleMiner()
    candidates = []
    domains = set(s.domain for s in signal_list if s.domain)
    
    for dom in domains:
        cluster = [s for s in signal_list if s.domain == dom]
        if len(cluster) >= 3:
            rule_dict = await miner.extract_rule([{"id": s.id, "payload": s.clean_payload} for s in cluster])
            if rule_dict:
                rule_dict["domain"] = dom
                rule_dict["id"] = f"cand_{dom}_{len(candidates)}"
                candidates.append(rule_dict)
                
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
