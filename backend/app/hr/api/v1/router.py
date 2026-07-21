"""
KAEOS HR Vertical — V1 API Router

Read endpoints plus the state-changing mutations/triggers for the recruiting
pipeline. Tenant is always derived from the authenticated context
(``Depends(get_tenant_id)``) — never a query param or a hardcoded "default".

AI actions that change state (candidate screening) run through the gated
``AgentExecutor`` pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate ->
Execute -> Audit) via the HR agents, and responses carry provenance / HITL
references so callers can trace or resolve them.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.hr.models.core import HREmployee
from app.hr.models.recruiting import (
    JobRequisition, Candidate, CandidateStage, ReqStatus,
)
from app.hr.models.time_attendance import TimeOffRequest
from app.hr.models.performance import PerformanceReview

router = APIRouter(prefix="/hr", tags=["Human Resources"])


# ── Request schemas ───────────────────────────────────────────────────────────

class RequisitionCreate(BaseModel):
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


class HITLDecision(BaseModel):
    reason: str = ""
    approver: str = "human"


# ── Core Employee Data ────────────────────────────────────────────────────────

@router.get("/employees", response_model=List[Dict[str, Any]])
async def list_employees(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id).limit(200))
    employees = q.scalars().all()
    return [{
        "id": e.id, "first_name": e.first_name, "last_name": e.last_name, "status": e.status,
        "email": e.email, "job_title": e.job_title,
        "location": e.location or ("Remote" if e.is_remote else None),
        "hire_date": e.hire_date.isoformat() if e.hire_date else None,
    } for e in employees]


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(HREmployee).where(HREmployee.tenant_id == tenant_id, HREmployee.id == employee_id)
    )
    employee = q.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {
        "id": employee.id, "email": employee.email,
        "first_name": employee.first_name, "last_name": employee.last_name,
        "status": employee.status, "job_title": employee.job_title,
        # "title" kept for legacy consumers
        "title": employee.job_title,
        "location": employee.location or ("Remote" if employee.is_remote else None),
        "hire_date": employee.hire_date.isoformat() if employee.hire_date else None,
    }


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
        actor=tenant.get("name"), actor_role=tenant.get("role"),
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
    req = (await db.execute(
        select(JobRequisition).where(
            JobRequisition.id == body.requisition_id,
            JobRequisition.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")

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
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="candidate", resource_id=candidate.id,
    )
    return {"id": candidate.id, "stage": candidate.stage.value}


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
    candidate = (await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    from app.hr.agents.recruiting_agent import RecruitingAgent

    candidate.stage = CandidateStage.AI_SCREENING
    db.add(candidate)
    await db.commit()

    agent = RecruitingAgent()
    result = await agent.screen_candidate(db, candidate_id)

    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
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
    candidate = (await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

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
    db.add(candidate)
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="candidate", resource_id=candidate_id,
    )
    return {"candidate_id": candidate_id, "stage": target.value}


# ── HITL approve / reject ─────────────────────────────────────────────────────

@router.post("/hitl/{execution_id}/approve")
async def hitl_approve(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Approve a pending HITL-gated HR execution."""
    tenant_id = tenant["tenant_id"]
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, True, body.approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
    )
    return {"execution_id": execution_id, "approved": True}


@router.post("/hitl/{execution_id}/reject")
async def hitl_reject(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Reject a pending HITL-gated HR execution."""
    tenant_id = tenant["tenant_id"]
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, False, body.approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
    )
    return {"execution_id": execution_id, "approved": False}


# ── Time & Attendance / Performance (reads) ───────────────────────────────────

@router.get("/time-off-requests")
async def list_time_off_requests(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TimeOffRequest).where(TimeOffRequest.tenant_id == tenant_id).limit(200))
    requests = q.scalars().all()
    return [{
        "id": r.id, "employee_id": r.employee_id, "status": r.status, "leave_type": r.leave_type,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "hours_requested": r.hours_requested,
    } for r in requests]


@router.get("/performance-reviews")
async def list_performance_reviews(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(PerformanceReview).where(PerformanceReview.tenant_id == tenant_id).limit(200))
    reviews = q.scalars().all()
    return [{"id": r.id, "employee_id": r.employee_id, "status": r.status,
             "manager_rating": r.manager_rating, "self_rating": r.self_rating} for r in reviews]


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_hr_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    emps = (await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id))).scalars().all()
    reqs = (await db.execute(select(JobRequisition).where(JobRequisition.tenant_id == tenant_id))).scalars().all()
    open_reqs = [r for r in reqs if (r.status.value if hasattr(r.status, "value") else r.status) == "OPEN"]
    candidates = (await db.execute(select(Candidate).where(Candidate.tenant_id == tenant_id))).scalars().all()

    # Derivable metrics from real rows; the rest stay None ("—" in the UI)
    # until a genuine data source (surveys, LMS) exists.
    from datetime import datetime, timezone as _tz

    now = datetime.now(_tz.utc)
    applications_this_month = sum(
        1 for c in candidates
        if c.applied_at and c.applied_at.year == now.year and c.applied_at.month == now.month
    )

    def _stage(c):
        return c.stage.value if hasattr(c.stage, "value") else str(c.stage)

    hired = sum(1 for c in candidates if _stage(c) == "HIRED")
    offers_out = sum(1 for c in candidates if _stage(c) == "OFFER_EXTENDED")
    offer_acceptance_rate = round(hired / (hired + offers_out) * 100, 1) if (hired + offers_out) else None

    def _emp_status(e):
        return e.status.value if hasattr(e.status, "value") else str(e.status)

    terminated = sum(1 for e in emps if _emp_status(e) == "TERMINATED" or e.termination_date)
    turnover_rate = round(terminated / len(emps) * 100, 1) if emps else None

    from app.models.fairness import FairnessAuditLog
    fairness_logs = (await db.execute(
        select(FairnessAuditLog).where(FairnessAuditLog.tenant_id == tenant_id)
    )).scalars().all()
    compliance_score = (
        round(sum(1 for l in fairness_logs if l.passed) / len(fairness_logs) * 100, 1)
        if fairness_logs else None
    )

    return {
        "total_employees": len(emps),
        "open_positions": len(open_reqs),
        "total_candidates": len(candidates),
        "applications_this_month": applications_this_month,
        "avg_time_to_fill": None,
        "offer_acceptance_rate": offer_acceptance_rate,
        "satisfaction_score": None,
        "turnover_rate": turnover_rate,
        "training_completion": None,
        "compliance_score": compliance_score,
    }

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition, list_workflow_events,
)
from app.hr.services.analytics import hr_analytics  # noqa: E402
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_hr_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed headcount, funnel and time-off KPIs for the HR cockpit."""
    return await hr_analytics(db, tenant_id)


@router.get("/workflows")
async def get_hr_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines — candidate stages stay on /candidates/{id}/advance."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_hr_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for HR entities."""
    return await list_workflow_events(db, tenant_id, domain="hr",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/time-off-requests/{request_id}/transition")
async def transition_time_off_request(
    request_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Approve / deny / cancel a time-off request through the guarded engine."""
    return await apply_transition(db, WORKFLOW_SPECS["time_off_request"], request_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/requisitions/{requisition_id}/transition")
async def transition_requisition(
    requisition_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a job requisition through draft → approval → open → filled."""
    return await apply_transition(db, WORKFLOW_SPECS["job_requisition"], requisition_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation — time off
# ═══════════════════════════════════════════════════════════════════════
from datetime import date as _date  # noqa: E402


class TimeOffCreate(BaseModel):
    employee_id: str
    leave_type: str = Field("PTO", pattern="^(PTO|SICK|MATERNITY|PATERNITY|BEREAVEMENT|JURY_DUTY|UNPAID)$")
    start_date: _date
    end_date: _date
    hours_requested: float = Field(..., gt=0)
    reason: Optional[str] = Field(None, max_length=512)


@router.post("/time-off-requests", status_code=201)
async def create_time_off_request(
    body: TimeOffCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """File a time-off request (starts REQUESTED; decide via /transition)."""
    tenant_id = tenant["tenant_id"]
    if body.end_date < body.start_date:
        raise HTTPException(422, "end_date must be on or after start_date")
    emp_q = await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))
    if not emp_q.scalar_one_or_none():
        raise HTTPException(404, "Employee not found")
    req = TimeOffRequest(
        tenant_id=tenant_id, employee_id=body.employee_id,
        leave_type=body.leave_type, start_date=body.start_date,
        end_date=body.end_date, hours_requested=body.hours_requested,
        reason=body.reason,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="time_off_request", resource_id=req.id,
    )
    return {"id": req.id, "employee_id": req.employee_id,
            "status": req.status.value if hasattr(req.status, "value") else str(req.status),
            "leave_type": req.leave_type.value if hasattr(req.leave_type, "value") else str(req.leave_type),
            "hours_requested": req.hours_requested}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_hr(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 hr entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
