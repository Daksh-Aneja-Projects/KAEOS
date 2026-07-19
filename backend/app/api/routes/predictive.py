"""KAEOS 10X — Predictive Operations API"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.domain import Signal, SkillExecution
from app.services.predictive_ops import PredictiveOpsEngine

router = APIRouter(prefix="/predictive", tags=["KAEOS 10X — Predictive Ops"])

@router.post("/analyze-signal/{signal_id}")
async def analyze_and_predict(signal_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """
    Analyzes a specific signal for latent intent and triggers 
    a zero-prompt execution if highly confident.
    """
    # Scope the lookup to the caller's tenant. Without this filter any
    # authenticated user could analyse (and trigger zero-prompt execution
    # against) another tenant's signal by id — a cross-tenant leak on any
    # non-RLS (SQLite) deployment.
    signal_q = await db.execute(
        select(Signal).where(Signal.id == signal_id, Signal.tenant_id == tenant_id)
    )
    signal = signal_q.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
        
    intent = await PredictiveOpsEngine.analyze_signal_for_intent(db, signal)
    
    if intent:
        # Trigger execution based on intent
        execution = await PredictiveOpsEngine.trigger_zero_prompt_execution(db, intent)
        return {
            "status": "INTENT_DETECTED",
            "intent": {
                "type": intent.intent_type,
                "confidence": intent.confidence,
                "recommended_skill": intent.recommended_skill_id
            },
            "action": "ZERO_PROMPT_EXECUTION_QUEUED",
            "execution_id": execution.id,
            "hitl_required": execution.hitl_required
        }
        
    return {
        "status": "NO_LATENT_INTENT",
        "message": "Signal processed. No automated action predicted."
    }

@router.get("/ghost-executions")
async def get_ghost_executions(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Retrieve all zero-prompt (ghost) executions."""
    # Scoped: was returning every tenant's ghost executions (with task_intent
    # and context) to any caller.
    exec_q = await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.route_type == "ZERO_PROMPT_AUTO",
        )
        .order_by(SkillExecution.started_at.desc())
        .limit(50)
    )
    executions = exec_q.scalars().all()
    
    return {
        "ghost_executions": [
            {
                "id": e.id,
                "skill_name": e.skill_id_name,
                "status": e.status,
                "task_intent": e.task_intent,
                "context": e.context,
                "hitl_required": e.hitl_required,
                "started_at": e.started_at,
            }
            for e in executions
        ]
    }

@router.post("/discover-patterns")
async def discover_patterns(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Triggers the Pattern Discovery Engine to find latent workflow opportunities."""
    from app.services.pattern_discovery_engine import PatternDiscoveryEngine

    # Build outcome records from real execution exhaust
    exec_q = await db.execute(
        select(SkillExecution)
        .where(SkillExecution.tenant_id == tenant_id)
        .order_by(SkillExecution.started_at.desc())
        .limit(500)
    )
    records = [
        {
            "feature_inputs": {
                "duration_ms": float(e.duration_ms or 0),
                "hitl_required": 1.0 if e.hitl_required else 0.0,
                "confidence_delta": float(e.confidence_delta or 0.0),
            },
            "success_score": 100.0 if "SUCCESS" in (e.status or "") else 0.0,
            "domain": e.skill_id_name or "general",
            "enterprise_type": "Technology",
        }
        for e in exec_q.scalars().all()
    ]

    engine = PatternDiscoveryEngine(records)
    patterns = engine.discover_patterns()

    return {
        "status": "DISCOVERY_COMPLETE",
        "records_analyzed": len(records),
        "patterns_found": len(patterns),
        "insights": patterns
    }
