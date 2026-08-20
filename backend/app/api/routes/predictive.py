"""Predictive operations: latent intent detection and forward-looking ops."""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.execution_status import SUCCEEDED_STATUSES
from app.models.domain import Signal, SkillExecution
from app.models.jobs import Job
from app.services.predictive_ops import PredictiveOpsEngine
from app.core.tenant import approver_identity

router = APIRouter(prefix="/predictive", tags=["Predictive Ops"])

@router.post("/analyze-signal/{signal_id}")
async def analyze_and_predict(signal_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """
    Analyzes a specific signal for latent intent and triggers
    a zero-prompt execution if highly confident.
    """
    tenant_id = tenant["tenant_id"]
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
        # Enqueue for governed execution: the durable job runs the skill
        # through the full gate pipeline, which decides HITL — a prediction
        # cannot pre-claim (or pre-waive) human review.
        job_id = await PredictiveOpsEngine.trigger_zero_prompt_execution(db, intent)
        await record_security_event(
            tenant_id=tenant_id, event_type="AGENT_EXEC", action="EXECUTE",
            actor=approver_identity(tenant), actor_role=tenant.get("role"),
            resource_type="zero_prompt_job", resource_id=job_id,
        )
        return {
            "status": "INTENT_DETECTED",
            "intent": {
                "type": intent.intent_type,
                "confidence": intent.confidence,
                "recommended_skill": intent.recommended_skill_id
            },
            "action": "ZERO_PROMPT_EXECUTION_QUEUED",
            "job_id": job_id,
        }
        
    return {
        "status": "NO_LATENT_INTENT",
        "message": "Signal processed. No automated action predicted."
    }

@router.get("/ghost-executions")
async def get_ghost_executions(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Zero-prompt (ghost) executions: the runs KAEOS initiated on its own.

    Reads the durable job queue — the source of truth since predictions became
    governed jobs. A job's lifecycle (QUEUED → RUNNING → SUCCEEDED | FAILED) is
    the ghost's honest status; the gated SkillExecution the handler creates
    appears in every normal execution surface. hitl_required is null here
    because the gate pipeline decides it at run time, not the prediction.
    """
    jobs = (await db.execute(
        select(Job)
        .where(Job.tenant_id == tenant_id, Job.job_type == "zero_prompt_execution")
        .order_by(Job.created_at.desc())
        .limit(50)
    )).scalars().all()

    return {
        "ghost_executions": [
            {
                "id": j.id,
                "skill_name": (j.payload or {}).get("skill_id"),
                "status": "EXECUTED" if j.status == "SUCCEEDED" else j.status,
                "task_intent": "Auto-predicted from latent intent analysis",
                "context": (j.payload or {}).get("context"),
                "hitl_required": None,
                "started_at": j.created_at,
            }
            for j in jobs
        ]
    }

@router.post("/discover-patterns", dependencies=[Depends(require_role("operator"))])
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
            # Was this a success? The named set, not a substring test: "SUCCESS"
            # in status would also match any future member that merely contains
            # the word (a FAILED_AFTER_SUCCESS would have scored 100).
            "success_score": 100.0 if (e.status or "") in SUCCEEDED_STATUSES else 0.0,
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
