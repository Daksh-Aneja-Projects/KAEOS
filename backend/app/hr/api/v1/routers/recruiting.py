"""KAEOS HR V1 — recruiting

Recruiting: requisitions, candidates, AI screening, the fairness sweep
and the hand-guarded candidate-stage funnel.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.hr.models.recruiting import (
    JobRequisition, Candidate, CandidateStage, ReqStatus,
)

router = APIRouter()


# ── Request schemas ───────────────────────────────────────────────────────────

class RequisitionCreate(BaseModel):
    # procurement declares a RequisitionCreate too, so pydantic publishes BOTH
    # under module-qualified component names. The published name is part of the
    # frozen HTTP surface, so pin the pre-split module path here rather than let
    # an internal file move rename a client-visible schema. (Same reason
    # make_department_workflow_router pins __name__/__doc__ on its generated
    # endpoints.) Must be set in the class body: pydantic builds the schema ref
    # at class creation, so assigning __module__ afterwards is too late.
    __module__ = "app.hr.api.v1.router"

    title: str
    department: str
    hiring_manager_id: str
    job_description: str
    headcount: int = 1
    requirements: List[str] = Field(default_factory=list)
    target_salary_min: Optional[int] = None
    target_salary_max: Optional[int] = None


class CandidateCreate(BaseModel):
    requisition_id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    resume_path: Optional[str] = None


class StageAdvance(BaseModel):
    target_stage: str
    # Required (non-empty) when target_stage is REJECTED: a rejection is a
    # terminal adverse action and must carry a documented reason.
    reason: Optional[str] = None


# ── Recruiting: reads ─────────────────────────────────────────────────────────

@router.get("/requisitions")
async def list_requisitions(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(JobRequisition).where(JobRequisition.tenant_id == tenant_id).limit(200))
    reqs = q.scalars().all()
    return [{"id": r.id, "title": r.title, "status": r.status, "headcount": r.headcount,
             "department": r.department,
             "target_salary_min": r.target_salary_min, "target_salary_max": r.target_salary_max} for r in reqs]


@router.get("/candidates")
async def list_candidates(
    tenant_id: str = Depends(get_tenant_id),
    requisition_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Candidate).where(Candidate.tenant_id == tenant_id)
    if requisition_id:
        stmt = stmt.where(Candidate.requisition_id == requisition_id)
    candidates = (await db.execute(stmt.limit(200))).scalars().all()
    return [{
        "id": c.id,
        "requisition_id": c.requisition_id,
        "name": f"{c.first_name} {c.last_name}",
        "email": c.email,
        "stage": c.stage.value if hasattr(c.stage, "value") else c.stage,
        "ai_score": c.ai_score,
        "ai_summary": c.ai_summary,
        "ai_red_flags": c.ai_red_flags or [],
    } for c in candidates]


# ── Recruiting: mutations & triggers ──────────────────────────────────────────

@router.post("/requisitions", status_code=201)
async def create_requisition(
    body: RequisitionCreate,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new job requisition (opens it for candidates)."""
    tenant_id = tenant["tenant_id"]
    req = JobRequisition(
        tenant_id=tenant_id,
        title=body.title,
        department=body.department,
        hiring_manager_id=body.hiring_manager_id,
        job_description=body.job_description,
        headcount=body.headcount,
        requirements=body.requirements,
        target_salary_min=body.target_salary_min,
        target_salary_max=body.target_salary_max,
        status=ReqStatus.OPEN,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="requisition", resource_id=req.id,
    )
    return {"id": req.id, "title": req.title, "status": req.status.value}


@router.post("/candidates", status_code=201)
async def add_candidate(
    body: CandidateCreate,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Add a candidate to a requisition (scoped to the caller's tenant)."""
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, JobRequisition, body.requisition_id, tenant_id, detail="Requisition not found")

    candidate = Candidate(
        tenant_id=tenant_id,
        requisition_id=body.requisition_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        resume_path=body.resume_path,
        stage=CandidateStage.APPLIED,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="candidate", resource_id=candidate.id,
    )
    return {"id": candidate.id, "stage": candidate.stage.value}


# REVIEW: hr's gated agent endpoints have neither the ValueError -> 404 nor the
# 500 handler its siblings share. Their bodies are bespoke (pre-fetch, mutate,
# custom response shape) so they are not instances of the run_agent_endpoint()
# family; the missing handlers are a real gap, quarantined as a behaviour change.
@router.post("/candidates/{candidate_id}/screen")
async def trigger_screening(
    candidate_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger AI screening for a candidate through the gated 7-gate pipeline.

    Returns the evaluation plus a provenance/execution reference. If a gate
    (fairness/compliance/debate) or HITL intervenes, the response carries the
    gated status and an ``execution_id`` that can be resolved via the HITL API.
    """
    tenant_id = tenant["tenant_id"]
    candidate = await get_or_404(db, Candidate, candidate_id, tenant_id, detail="Candidate not found")

    from app.hr.agents.recruiting_agent import RecruitingAgent

    candidate.stage = CandidateStage.AI_SCREENING
    db.add(candidate)
    await db.commit()

    agent = RecruitingAgent()
    result = await agent.screen_candidate(db, candidate_id)

    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="candidate", resource_id=candidate_id,
    )

    # Gated / non-clean outcome — surface status + provenance reference for HITL.
    if result.get("gated"):
        return {
            "candidate_id": candidate_id,
            "screening": "gated",
            "status": result.get("status"),
            "provenance": {"execution_id": (result.get("detail") or {}).get("execution_id")},
            "hitl": {"execution_id": (result.get("detail") or {}).get("execution_id")},
        }

    return {
        "candidate_id": candidate_id,
        "screening": "complete",
        "evaluation": {k: v for k, v in result.items() if k not in ("status", "execution_id")},
        "provenance": {"execution_id": result.get("execution_id")},
    }


@router.post("/requisitions/{requisition_id}/fairness-sweep")
async def run_requisition_fairness_sweep_route(
    requisition_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Run the statistical disparate-impact sweep for a requisition's cohort.

    Aggregates decided candidates' voluntary self-ID into cohort counts and runs
    the four-fifths test through the gated executor. An adverse-impact finding
    returns PENDING_HITL with an ``execution_id`` resolvable via the HITL API; a
    sub-threshold cohort returns INSUFFICIENT_GROUPS (advisory, non-blocking).
    """
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, JobRequisition, requisition_id, tenant_id, detail="Requisition not found")

    from app.hr.services.fairness_sweep import run_requisition_fairness_sweep

    result = await run_requisition_fairness_sweep(db, tenant_id, requisition_id)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="requisition", resource_id=requisition_id,
        details={"sweep_status": result.get("status")},
    )
    return {
        "requisition_id": requisition_id,
        "status": result.get("status"),
        "execution_id": result.get("execution_id"),
        "flagged_attributes": result.get("flagged_attributes"),
        "decided_total": result.get("decided_total"),
        "reason": result.get("reason"),
    }


# Legal, non-skipping forward transitions for the recruiting funnel.
_STAGE_ORDER = [
    CandidateStage.APPLIED, CandidateStage.AI_SCREENING, CandidateStage.RECRUITER_SCREEN,
    CandidateStage.HM_INTERVIEW, CandidateStage.PANEL_INTERVIEW, CandidateStage.OFFER_PREP,
    CandidateStage.OFFER_EXTENDED, CandidateStage.HIRED,
]
_TERMINAL_STAGES = {CandidateStage.HIRED, CandidateStage.REJECTED, CandidateStage.WITHDRAWN}


@router.post("/candidates/{candidate_id}/advance")
async def advance_candidate_stage(
    candidate_id: str,
    body: StageAdvance,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Advance (or reject/withdraw) a candidate's pipeline stage."""
    tenant_id = tenant["tenant_id"]
    candidate = await get_or_404(db, Candidate, candidate_id, tenant_id, detail="Candidate not found")

    try:
        target = CandidateStage(body.target_stage)
    except ValueError:
        valid = [s.value for s in CandidateStage]
        raise HTTPException(status_code=422, detail=f"Invalid stage. Valid: {valid}")

    current = candidate.stage if isinstance(candidate.stage, CandidateStage) else CandidateStage(candidate.stage)
    if current in _TERMINAL_STAGES:
        raise HTTPException(status_code=409, detail=f"Candidate is in terminal stage {current.value}")

    # Rejection/withdrawal is always allowed; otherwise enforce forward-only funnel.
    if target not in (CandidateStage.REJECTED, CandidateStage.WITHDRAWN):
        if target in _STAGE_ORDER and current in _STAGE_ORDER:
            if _STAGE_ORDER.index(target) <= _STAGE_ORDER.index(current):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot move from {current.value} to {target.value} (not a forward transition)",
                )

    candidate.stage = target

    # A move to REJECTED is a terminal adverse action. The agent screening path
    # runs the EEOC fairness gate; a manual reject must too, or it becomes an
    # ungoverned adverse action with no fairness check. Require a documented
    # reason and run the four-fifths adverse-impact checker over the requisition
    # cohort (this pending rejection is folded in via autoflush of the stage set
    # above). Fail-closed: block if the reason is missing or the gate blocks.
    reason = (body.reason or "").strip()
    if target == CandidateStage.REJECTED:
        if not reason:
            raise HTTPException(
                status_code=422,
                detail="A documented reason is required to reject a candidate (adverse action).",
            )
        from app.hr.services.fairness_sweep import build_cohort_outcomes
        from app.compliance.registry import run_checks
        built = await build_cohort_outcomes(db, tenant_id, candidate.requisition_id)
        gate = run_checks(["EEOC"], {"cohort_outcomes": built["cohorts"]})
        if not gate["verified"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "EEOC adverse-impact gate blocked this rejection; route to fairness review.",
                    "blocking": gate["blocking"],
                },
            )

    db.add(candidate)
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="candidate", resource_id=candidate_id,
        details={"target_stage": target.value, "reason": reason} if target == CandidateStage.REJECTED else None,
    )
    return {"candidate_id": candidate_id, "stage": target.value}
