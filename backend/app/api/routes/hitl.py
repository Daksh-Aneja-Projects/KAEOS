from app.core.tenant import get_tenant_id
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db

router = APIRouter(prefix="/hitl", tags=["HITL"])


class HITLResolutionRequest(BaseModel):
    execution_id: str
    approved: bool
    reason: str = ""
    approver: str = "human"


@router.get("/status/{execution_id}")
async def get_hitl_status(
    execution_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get the status of a HITL approval (for polling)."""
    from app.services.hitl_manager import hitl_manager
    status = await hitl_manager.get_hitl_status(execution_id, tenant_id=tenant_id)
    if status["status"] == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Execution ID not found")
    return status


@router.post("/resolve")
async def resolve_hitl(req: HITLResolutionRequest, tenant_id: str = Depends(get_tenant_id)):
    """Resolve a pending HITL approval (Redis-backed, restart-safe)."""
    from app.services.hitl_manager import hitl_manager
    success = await hitl_manager.resolve_hitl(
        req.execution_id, req.approved, req.approver, req.reason, tenant_id=tenant_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Execution ID not found in pending HITL requests")
    return {"status": "success", "execution_id": req.execution_id, "approved": req.approved}


@router.post("/{execution_id}/approve")
async def approve_hitl(
    execution_id: str,
    data: dict,
    tenant_id: str = Depends(get_tenant_id),
):
    """Approve a pending HITL request."""
    from app.services.hitl_manager import hitl_manager
    reason = data.get("reason", "")
    approver = data.get("approver", "human")
    success = await hitl_manager.resolve_hitl(
        execution_id, approved=True, approver=approver, reason=reason, tenant_id=tenant_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Execution ID not found")
    return {"status": "approved", "execution_id": execution_id}


@router.post("/{execution_id}/reject")
async def reject_hitl(
    execution_id: str,
    data: dict,
    tenant_id: str = Depends(get_tenant_id),
):
    """Reject a pending HITL request."""
    from app.services.hitl_manager import hitl_manager
    reason = data.get("reason", "")
    approver = data.get("approver", "human")
    success = await hitl_manager.resolve_hitl(
        execution_id, approved=False, approver=approver, reason=reason, tenant_id=tenant_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Execution ID not found")
    return {"status": "rejected", "execution_id": execution_id}


@router.get("/pending")
async def list_pending_hitl(tenant_id: str = Depends(get_tenant_id)):
    """List all pending HITL approvals for this tenant (Redis or memory fallback)."""
    from app.services.hitl_manager import hitl_manager
    pending = await hitl_manager.list_pending(tenant_id)
    # don't ship the full stored context over the wire
    slim = [
        {**{k: v for k, v in p.items() if k not in ("context", "skill_def")},
         "execution_id": p.get("exec_id")}
        for p in pending
    ]
    return {"pending": slim, "count": len(slim)}


@router.get("/decision-feed")
async def get_decision_feed(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Returns the latest HITL decisions combining debate transcripts and fairness logs."""
    from app.models.domain import SkillExecution
    # Fetch real HITL executions for this tenant
    res = await db.execute(
        select(SkillExecution)
        .where(SkillExecution.tenant_id == tenant_id, SkillExecution.hitl_required == True)
        .order_by(SkillExecution.started_at.desc())
        .limit(5)
    )
    execs = res.scalars().all()

    decision_feed = []
    for e in execs:
        decision_feed.append({
            "execution_id": e.id,
            "skill_id": e.skill_id_name,
            "status": e.agent_state,
            "hitl_required": e.hitl_required,
            "hitl_approved": e.hitl_approved,
            "hitl_approver": e.hitl_approver,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "task_intent": e.task_intent,
            "reasoning_chain": e.reasoning_chain or [],
        })

    # If no real HITL executions yet, return an informative empty state
    if not decision_feed:
        return {
            "message": "No HITL decisions recorded yet for this tenant.",
            "decisions": [],
        }

    return {"decisions": decision_feed}
