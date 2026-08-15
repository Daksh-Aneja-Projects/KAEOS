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
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.audit import record_security_event
from app.hr.models.core import HREmployee, EmployeeDocument, EmploymentStatus
from app.hr.models.recruiting import (
    JobRequisition, Candidate, CandidateStage, ReqStatus, Interview,
)
from app.hr.models.time_attendance import TimeOffRequest, Timesheet
from app.hr.models.performance import PerformanceReview, ReviewCycle
from app.hr.models.benefits import BenefitPlan, BenefitEnrollment, EnrollmentStatus as BenefitEnrollmentStatus
from app.hr.models.compensation import Compensation
from app.hr.models.onboarding import BoardingPlan, BoardingTask, BoardingType, TaskStatus
from app.hr.models.learning import Course, CourseEnrollment
from app.hr.models.employee_relations import ERCase, CaseStatus
from app.hr.models.workforce_planning import HeadcountPlan
from app.hr.models.payroll import PayrollRun, Payslip
from app.hr.models.compliance import ComplianceReport, ComplianceViolation
from app.hr.models.analytics import HRMetricSnapshot

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
    # DEPRECATED / IGNORED: the approver is derived from the authenticated
    # principal server-side (see hitl_approve/hitl_reject). Kept only so older
    # clients that still send it do not break; its value is never trusted.
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
    req = (await db.execute(
        select(JobRequisition).where(
            JobRequisition.id == requisition_id,
            JobRequisition.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")

    from app.hr.services.fairness_sweep import run_requisition_fairness_sweep

    result = await run_requisition_fairness_sweep(db, tenant_id, requisition_id)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
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
# INTENTIONALLY KEPT despite being unreachable from the current frontend (the
# HITLQueue UI resolves every domain's pending executions through the generic
# api.approveHITL/api.rejectHITL -> hitl_manager path, which is
# domain-agnostic and works fine for HR too). These HR-scoped routes stay as a
# stable, documented surface for API-only / integration callers who want an
# `/hr/...` URL rather than the generic one — same resolution, same audit
# trail, just namespaced. Delete only if that use case is confirmed dead too.

@router.post("/hitl/{execution_id}/approve")
async def hitl_approve(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Approve a pending HITL-gated HR execution.

    The approver recorded is the AUTHENTICATED principal — the client-supplied
    ``body.approver`` is ignored (a spoofable approver would undermine every
    HITL data point that feeds the safe-autonomy metric).
    """
    tenant_id = tenant["tenant_id"]
    approver = approver_identity(tenant)
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, True, approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
        details={"reason": body.reason},
    )
    return {"execution_id": execution_id, "approved": True, "approver": approver}


@router.post("/hitl/{execution_id}/reject")
async def hitl_reject(
    execution_id: str,
    body: HITLDecision,
    tenant: dict = Depends(require_role("operator")),
):
    """Reject a pending HITL-gated HR execution.

    Approver = authenticated principal; ``body.approver`` is ignored.
    """
    tenant_id = tenant["tenant_id"]
    approver = approver_identity(tenant)
    from app.services.hitl_manager import hitl_manager
    ok = await hitl_manager.resolve_hitl(
        execution_id, False, approver, body.reason, tenant_id=tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="No pending HITL request for that execution")
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="hitl_execution", resource_id=execution_id,
        details={"reason": body.reason},
    )
    return {"execution_id": execution_id, "approved": False, "approver": approver}


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


# ═══════════════════════════════════════════════════════════════════════
# Full-schema coverage — the other 9 model groups (Benefits, Compensation,
# Onboarding/Offboarding, Learning, Employee Relations, Workforce Planning,
# Payroll, Compliance, Analytics) plus Interviews/EmployeeDocuments/
# Timesheets and the 6 previously-dead HR agents (bound only to org-graph
# metadata nothing ever read — see workforce_generator.HR_AGENT_REGISTRY).
# Every mutation is tenant-scoped and real DB-backed logic; every agent
# trigger below persists its decision onto the entity, never just returns
# a dict and forgets it.
# ═══════════════════════════════════════════════════════════════════════
from datetime import datetime, timezone, timedelta  # noqa: E402


def _exec_id(result: Dict[str, Any]) -> Optional[str]:
    """Gated-executor results carry execution_id at top level when clean, or
    nested under 'detail' when gated — same shape trigger_screening handles."""
    return result.get("execution_id") or (result.get("detail") or {}).get("execution_id")


def _workflow_event(tenant_id: str, entity_type: str, entity_id: str, from_state: str, to_state: str, tenant: dict):
    """A WorkflowEvent row for mutations that carry a richer payload than the
    generic engine's transition endpoint can express (a rating + assessment,
    not just a bare to_state) — same audit trail, hand-built instead of via
    apply_transition."""
    from app.core.workflow import WorkflowEvent
    return WorkflowEvent(
        tenant_id=tenant_id, domain="hr", entity_type=entity_type, entity_id=entity_id,
        from_state=from_state, to_state=to_state,
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
    )


# ── Benefits Administration ───────────────────────────────────────────────────

class BenefitPlanCreate(BaseModel):
    name: str
    provider: str
    benefit_type: str = Field(..., pattern="^(HEALTH|DENTAL|VISION|LIFE_INSURANCE|RETIREMENT|FSA_HSA|PERKS)$")
    description: Optional[str] = None
    employee_cost_individual: float = 0.0
    employee_cost_family: float = 0.0
    employer_contribution: float = 0.0


@router.get("/benefit-plans")
async def list_benefit_plans(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(BenefitPlan).where(BenefitPlan.tenant_id == tenant_id, BenefitPlan.is_active == True).limit(200)
    )).scalars().all()
    return [{
        "id": p.id, "name": p.name, "provider": p.provider,
        "benefit_type": p.benefit_type.value if hasattr(p.benefit_type, "value") else str(p.benefit_type),
        "description": p.description,
        "employee_cost_individual": p.employee_cost_individual, "employee_cost_family": p.employee_cost_family,
        "employer_contribution": p.employer_contribution,
    } for p in rows]


@router.post("/benefit-plans", status_code=201)
async def create_benefit_plan(
    body: BenefitPlanCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    plan = BenefitPlan(
        tenant_id=tenant_id, name=body.name, provider=body.provider, benefit_type=body.benefit_type,
        description=body.description, employee_cost_individual=body.employee_cost_individual,
        employee_cost_family=body.employee_cost_family, employer_contribution=body.employer_contribution,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="benefit_plan", resource_id=plan.id)
    return {"id": plan.id, "name": plan.name}


class BenefitEnrollmentCreate(BaseModel):
    employee_id: str
    plan_id: str
    coverage_level: str = Field("INDIVIDUAL", pattern="^(INDIVIDUAL|INDIVIDUAL_PLUS_ONE|FAMILY)$")
    effective_date: _date
    covered_dependents: List[str] = Field(default_factory=list)


@router.get("/benefit-enrollments")
async def list_benefit_enrollments(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(BenefitEnrollment).where(BenefitEnrollment.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(BenefitEnrollment.employee_id == employee_id)
    rows = (await db.execute(stmt.limit(200))).scalars().all()
    return [{
        "id": e.id, "employee_id": e.employee_id, "plan_id": e.plan_id,
        "status": e.status.value if hasattr(e.status, "value") else str(e.status),
        "coverage_level": e.coverage_level,
        "effective_date": e.effective_date.isoformat() if e.effective_date else None,
        "agent_verified": e.agent_verified,
    } for e in rows]


@router.post("/benefit-enrollments", status_code=201)
async def create_benefit_enrollment(
    body: BenefitEnrollmentCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    plan = (await db.execute(select(BenefitPlan).where(
        BenefitPlan.id == body.plan_id, BenefitPlan.tenant_id == tenant_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Benefit plan not found")
    enrollment = BenefitEnrollment(
        tenant_id=tenant_id, employee_id=body.employee_id, plan_id=body.plan_id,
        coverage_level=body.coverage_level, effective_date=body.effective_date,
        covered_dependents=body.covered_dependents, status=BenefitEnrollmentStatus.PENDING,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="benefit_enrollment", resource_id=enrollment.id)
    return {"id": enrollment.id, "status": enrollment.status.value}


@router.post("/benefit-enrollments/{enrollment_id}/transition")
async def transition_benefit_enrollment(
    enrollment_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["benefit_enrollment"], enrollment_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/benefit-enrollments/{enrollment_id}/verify")
async def verify_benefit_enrollment(
    enrollment_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Benefits Agent (through the gated 7-gate pipeline) to verify an
    employee's eligibility for their enrolled plan, and persist the outcome
    onto the enrollment (agent_verified, and PENDING -> ACTIVE on a clean
    pass). Wires BenefitsAgent, previously bound only to dead org-graph
    metadata (HR_AGENT_REGISTRY['benefits'])."""
    tenant_id = tenant["tenant_id"]
    enrollment = (await db.execute(select(BenefitEnrollment).where(
        BenefitEnrollment.id == enrollment_id, BenefitEnrollment.tenant_id == tenant_id))).scalar_one_or_none()
    if not enrollment:
        raise HTTPException(404, "Enrollment not found")
    plan = (await db.execute(select(BenefitPlan).where(BenefitPlan.id == enrollment.plan_id))).scalar_one_or_none()
    emp = (await db.execute(select(HREmployee).where(HREmployee.id == enrollment.employee_id))).scalar_one_or_none()
    if not plan or not emp:
        raise HTTPException(404, "Linked plan or employee not found")

    from app.hr.agents.benefits_agent import BenefitsAgent
    agent = BenefitsAgent()
    result = await agent.execute_via_pipeline(db, tenant_id, {
        "action": "verify_enrollment_eligibility",
        "employee_name": f"{emp.first_name} {emp.last_name}",
        "plan_name": plan.name,
        "plan_type": plan.benefit_type.value if hasattr(plan.benefit_type, "value") else str(plan.benefit_type),
        "coverage_level": enrollment.coverage_level,
    })
    status = result.get("status")
    verified = status == "SUCCESS_CLEAN"
    if verified:
        enrollment.agent_verified = True
        current_status = enrollment.status.value if hasattr(enrollment.status, "value") else str(enrollment.status)
        if current_status == "PENDING":
            enrollment.status = BenefitEnrollmentStatus.ACTIVE
        db.add(enrollment)
        await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="benefit_enrollment", resource_id=enrollment_id,
        details={"verified": verified, "status": status})
    return {"enrollment_id": enrollment_id, "verified": verified, "status": status, "execution_id": _exec_id(result)}


# ── Compensation & Equity ─────────────────────────────────────────────────────

class CompensationCreate(BaseModel):
    employee_id: str
    comp_type: str = Field("SALARY", pattern="^(SALARY|HOURLY|COMMISSION|BONUS|EQUITY)$")
    base_amount: float = Field(..., gt=0)
    currency: str = "USD"
    target_bonus_pct: float = 0.0
    equity_grant: int = 0
    equity_type: Optional[str] = None
    vesting_schedule: Optional[str] = None
    effective_date: _date
    change_reason: Optional[str] = Field(None, max_length=128)


@router.get("/compensation")
async def list_compensation(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(Compensation).where(Compensation.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(Compensation.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(Compensation.effective_date.desc()).limit(200))).scalars().all()
    return [{
        "id": c.id, "employee_id": c.employee_id,
        "comp_type": c.comp_type.value if hasattr(c.comp_type, "value") else str(c.comp_type),
        "base_amount": c.base_amount, "currency": c.currency, "target_bonus_pct": c.target_bonus_pct,
        "equity_grant": c.equity_grant, "equity_type": c.equity_type, "vesting_schedule": c.vesting_schedule,
        "effective_date": c.effective_date.isoformat() if c.effective_date else None,
        "is_current": c.is_current, "change_reason": c.change_reason,
    } for c in rows]


@router.post("/compensation", status_code=201)
async def create_compensation(
    body: CompensationCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    # A new current record supersedes the previous one, so is_current stays a
    # real, queryable invariant instead of drifting stale with multiple rows.
    prior = (await db.execute(select(Compensation).where(
        Compensation.tenant_id == tenant_id, Compensation.employee_id == body.employee_id,
        Compensation.is_current == True,
    ))).scalars().all()
    for p in prior:
        p.is_current = False
        p.end_date = body.effective_date
        db.add(p)
    comp = Compensation(
        tenant_id=tenant_id, employee_id=body.employee_id, comp_type=body.comp_type, base_amount=body.base_amount,
        currency=body.currency, target_bonus_pct=body.target_bonus_pct, equity_grant=body.equity_grant,
        equity_type=body.equity_type, vesting_schedule=body.vesting_schedule, effective_date=body.effective_date,
        change_reason=body.change_reason, is_current=True,
    )
    db.add(comp)
    await db.commit()
    await db.refresh(comp)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="compensation", resource_id=comp.id)
    return {"id": comp.id, "base_amount": comp.base_amount}


@router.post("/compensation/{compensation_id}/market-analysis")
async def compensation_market_analysis(
    compensation_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Compensation Agent's market-band analysis and annotate the
    record with its reasoning. Never auto-writes base_amount — a human must
    approve any pay change; the agent only informs. Wires CompensationAgent,
    previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    comp = (await db.execute(select(Compensation).where(
        Compensation.id == compensation_id, Compensation.tenant_id == tenant_id))).scalar_one_or_none()
    if not comp:
        raise HTTPException(404, "Compensation record not found")
    emp = (await db.execute(select(HREmployee).where(HREmployee.id == comp.employee_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Linked employee not found")

    from app.hr.agents.compensation_agent import CompensationAgent
    agent = CompensationAgent()
    # ponytail: Compensation stores a single point value, not a band, so a
    # +/-10% envelope around the real current pay stands in for "current
    # band" here — upgrade to real min/max columns if banded comp is modeled.
    current_band = {"min": round(comp.base_amount * 0.9, 2), "max": round(comp.base_amount * 1.1, 2)}
    analysis = await agent.analyze_salary_band(emp.job_title, emp.location or "Remote", current_band)

    reasoning = str(analysis.get("reasoning") or "")[:100]
    if reasoning:
        comp.change_reason = f"AI market analysis: {reasoning}"
        db.add(comp)
        await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="compensation", resource_id=compensation_id,
        details={"is_competitive": analysis.get("is_competitive")})
    return {"compensation_id": compensation_id, "analysis": analysis}


# ── Onboarding & Offboarding (BoardingPlan / BoardingTask) ────────────────────

_DEFAULT_ONBOARDING_TASKS = [
    "Complete I-9 and W-4 paperwork", "Provision laptop and system accounts",
    "Complete employee handbook acknowledgment", "30-60-90 plan with manager",
    "Benefits enrollment",
]
_DEFAULT_OFFBOARDING_TASKS = [
    "Revoke system access", "Return company equipment",
    "Final paycheck and COBRA notice", "Exit interview",
]


class BoardingPlanCreate(BaseModel):
    employee_id: str
    plan_type: str = Field("ONBOARDING", pattern="^(ONBOARDING|OFFBOARDING|CROSSBOARDING)$")
    start_date: datetime
    target_completion_date: Optional[datetime] = None
    tasks: List[str] = Field(default_factory=list)  # custom task titles; defaults used when empty


@router.get("/boarding-plans")
async def list_boarding_plans(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(BoardingPlan).where(BoardingPlan.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(BoardingPlan.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(BoardingPlan.start_date.desc()).limit(200))).scalars().all()
    return [{
        "id": p.id, "employee_id": p.employee_id,
        "plan_type": p.plan_type.value if hasattr(p.plan_type, "value") else str(p.plan_type),
        "status": p.status, "total_tasks": p.total_tasks, "completed_tasks": p.completed_tasks,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "target_completion_date": p.target_completion_date.isoformat() if p.target_completion_date else None,
    } for p in rows]


@router.post("/boarding-plans", status_code=201)
async def create_boarding_plan(
    body: BoardingPlanCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    titles = body.tasks or (
        _DEFAULT_ONBOARDING_TASKS if body.plan_type == "ONBOARDING"
        else _DEFAULT_OFFBOARDING_TASKS if body.plan_type == "OFFBOARDING" else []
    )
    plan = BoardingPlan(
        tenant_id=tenant_id, employee_id=body.employee_id, plan_type=body.plan_type,
        start_date=body.start_date, target_completion_date=body.target_completion_date,
        total_tasks=len(titles), completed_tasks=0, status="ACTIVE",
    )
    db.add(plan)
    await db.flush()
    for title in titles:
        db.add(BoardingTask(
            tenant_id=tenant_id, plan_id=plan.id, title=title,
            due_date=body.target_completion_date or body.start_date, status=TaskStatus.PENDING,
        ))
    await db.commit()
    await db.refresh(plan)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="boarding_plan", resource_id=plan.id)
    return {"id": plan.id, "total_tasks": plan.total_tasks}


class BoardingTaskCreate(BaseModel):
    plan_id: str
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: datetime


@router.get("/boarding-tasks")
async def list_boarding_tasks(
    plan_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(BoardingTask).where(BoardingTask.tenant_id == tenant_id)
    if plan_id:
        stmt = stmt.where(BoardingTask.plan_id == plan_id)
    rows = (await db.execute(stmt.order_by(BoardingTask.due_date.asc()).limit(200))).scalars().all()
    return [{
        "id": t.id, "plan_id": t.plan_id, "title": t.title, "description": t.description,
        "assignee_id": t.assignee_id, "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "is_automated": t.is_automated, "automation_result": t.automation_result,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    } for t in rows]


@router.post("/boarding-tasks", status_code=201)
async def create_boarding_task(
    body: BoardingTaskCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    plan = (await db.execute(select(BoardingPlan).where(
        BoardingPlan.id == body.plan_id, BoardingPlan.tenant_id == tenant_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Boarding plan not found")
    task = BoardingTask(
        tenant_id=tenant_id, plan_id=body.plan_id, title=body.title, description=body.description,
        assignee_id=body.assignee_id, due_date=body.due_date, status=TaskStatus.PENDING,
    )
    db.add(task)
    plan.total_tasks = (plan.total_tasks or 0) + 1
    db.add(plan)
    await db.commit()
    await db.refresh(task)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="boarding_task", resource_id=task.id)
    return {"id": task.id, "status": task.status.value}


@router.post("/boarding-tasks/{task_id}/transition")
async def transition_boarding_task(
    task_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["boarding_task"], task_id, body.to_state, tenant, note=body.note)
    if body.to_state in ("COMPLETED", "SKIPPED"):
        # Roll the parent plan's progress counter — derived from the sibling
        # tasks, never user-entered — and auto-close it once every task lands.
        task = (await db.execute(select(BoardingTask).where(BoardingTask.id == task_id))).scalar_one_or_none()
        if task:
            plan = (await db.execute(select(BoardingPlan).where(
                BoardingPlan.id == task.plan_id, BoardingPlan.tenant_id == tenant["tenant_id"]))).scalar_one_or_none()
            if plan:
                done = (await db.execute(select(sqlfunc.count()).select_from(BoardingTask).where(
                    BoardingTask.plan_id == plan.id,
                    BoardingTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED]),
                ))).scalar() or 0
                plan.completed_tasks = done
                if plan.total_tasks and done >= plan.total_tasks:
                    plan.status = "COMPLETED"
                db.add(plan)
                await db.commit()
    return result


class OnboardingCheckinBody(BaseModel):
    week_num: int = Field(..., ge=1, le=26)
    response: str = Field("", max_length=4000)


@router.post("/employees/{employee_id}/onboarding-checkin")
async def onboarding_checkin(
    employee_id: str, body: OnboardingCheckinBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Onboarding Agent's week-N check-in through the gated 7-gate
    pipeline. Wires OnboardingAgent, previously bound only to dead org-graph
    metadata (HR_AGENT_REGISTRY['onboarding'])."""
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    from app.hr.agents.onboarding_agent import OnboardingAgent
    agent = OnboardingAgent()
    result = await agent.check_in_with_new_hire(db, employee_id, body.week_num, body.response)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="hr_employee", resource_id=employee_id,
        details={"week_num": body.week_num, "status": result.get("status")})
    return {"employee_id": employee_id, "week_num": body.week_num, **result}


class ExitInterviewBody(BaseModel):
    survey_responses: Dict[str, str]


@router.post("/employees/{employee_id}/offboarding-exit-interview")
async def offboarding_exit_interview(
    employee_id: str, body: ExitInterviewBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Offboarding Agent's exit-interview analysis and persist it onto
    the employee's offboarding plan (creating the plan + an Exit Interview
    task the first time this runs for them). Wires OffboardingAgent,
    previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")

    from app.hr.agents.offboarding_agent import OffboardingAgent
    agent = OffboardingAgent()
    analysis = await agent.analyze_exit_interview(employee_id, body.survey_responses)

    plan = (await db.execute(select(BoardingPlan).where(
        BoardingPlan.tenant_id == tenant_id, BoardingPlan.employee_id == employee_id,
        BoardingPlan.plan_type == BoardingType.OFFBOARDING,
    ).order_by(BoardingPlan.start_date.desc()))).scalars().first()
    if not plan:
        plan = BoardingPlan(
            tenant_id=tenant_id, employee_id=employee_id, plan_type=BoardingType.OFFBOARDING,
            start_date=datetime.now(timezone.utc), total_tasks=0, completed_tasks=0, status="ACTIVE",
        )
        db.add(plan)
        await db.flush()

    task = (await db.execute(select(BoardingTask).where(
        BoardingTask.plan_id == plan.id, BoardingTask.title == "Exit Interview",
    ))).scalar_one_or_none()
    if not task:
        task = BoardingTask(
            tenant_id=tenant_id, plan_id=plan.id, title="Exit Interview",
            due_date=datetime.now(timezone.utc), status=TaskStatus.PENDING,
        )
        db.add(task)
        plan.total_tasks = (plan.total_tasks or 0) + 1

    task.automation_result = analysis
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc)
    task.is_automated = True
    task.automation_action = "analyze_exit_interview"
    db.add(task)

    done = (await db.execute(select(sqlfunc.count()).select_from(BoardingTask).where(
        BoardingTask.plan_id == plan.id, BoardingTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED]),
    ))).scalar() or 0
    plan.completed_tasks = done
    if plan.total_tasks and done >= plan.total_tasks:
        plan.status = "COMPLETED"
    db.add(plan)
    await db.commit()

    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="hr_employee", resource_id=employee_id,
        details={"boarding_plan_id": plan.id})
    return {"employee_id": employee_id, "boarding_plan_id": plan.id, "task_id": task.id, "analysis": analysis}


# ── Learning & Development ────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    provider: Optional[str] = None
    is_required_for_compliance: bool = False
    estimated_minutes: int = Field(60, gt=0)


@router.get("/courses")
async def list_courses(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Course).where(Course.tenant_id == tenant_id).limit(200))).scalars().all()
    return [{
        "id": c.id, "title": c.title, "description": c.description, "provider": c.provider,
        "is_required_for_compliance": c.is_required_for_compliance, "estimated_minutes": c.estimated_minutes,
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
    } for c in rows]


@router.post("/courses", status_code=201)
async def create_course(
    body: CourseCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    course = Course(
        tenant_id=tenant_id, title=body.title, description=body.description, provider=body.provider,
        is_required_for_compliance=body.is_required_for_compliance, estimated_minutes=body.estimated_minutes,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="course", resource_id=course.id)
    return {"id": course.id, "title": course.title}


class CourseEnrollmentCreate(BaseModel):
    employee_id: str
    course_id: str
    due_date: Optional[datetime] = None


@router.get("/course-enrollments")
async def list_course_enrollments(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(CourseEnrollment).where(CourseEnrollment.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(CourseEnrollment.employee_id == employee_id)
    rows = (await db.execute(stmt.limit(200))).scalars().all()
    return [{
        "id": e.id, "employee_id": e.employee_id, "course_id": e.course_id,
        "status": e.status.value if hasattr(e.status, "value") else str(e.status),
        "progress_pct": e.progress_pct, "due_date": e.due_date.isoformat() if e.due_date else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    } for e in rows]


@router.post("/course-enrollments", status_code=201)
async def create_course_enrollment(
    body: CourseEnrollmentCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    course = (await db.execute(select(Course).where(
        Course.id == body.course_id, Course.tenant_id == tenant_id))).scalar_one_or_none()
    if not course:
        raise HTTPException(404, "Course not found")
    enrollment = CourseEnrollment(
        tenant_id=tenant_id, employee_id=body.employee_id, course_id=body.course_id, due_date=body.due_date,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="course_enrollment", resource_id=enrollment.id)
    return {"id": enrollment.id, "status": enrollment.status.value}


@router.post("/course-enrollments/{enrollment_id}/transition")
async def transition_course_enrollment(
    enrollment_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["course_enrollment"], enrollment_id,
                                    body.to_state, tenant, note=body.note)
    if body.to_state == "COMPLETED":
        enrollment = (await db.execute(select(CourseEnrollment).where(
            CourseEnrollment.id == enrollment_id, CourseEnrollment.tenant_id == tenant["tenant_id"],
        ))).scalar_one_or_none()
        if enrollment:
            enrollment.progress_pct = 100.0
            enrollment.completed_at = datetime.now(timezone.utc)
            db.add(enrollment)
            await db.commit()
    return result


# ── Employee Relations ─────────────────────────────────────────────────────────

class ERCaseCreate(BaseModel):
    title: str
    description: str
    reporter_id: Optional[str] = None
    accused_id: Optional[str] = None
    category: str = Field(..., pattern="^(HARASSMENT|POLICY_VIOLATION|DISPUTE|DISCRIMINATION|SAFETY|OTHER)$")
    severity: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


@router.get("/er-cases")
async def list_er_cases(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ERCase).where(ERCase.tenant_id == tenant_id).order_by(ERCase.opened_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": c.id, "title": c.title, "category": c.category,
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        "severity": c.severity.value if hasattr(c.severity, "value") else str(c.severity),
        "reporter_id": c.reporter_id, "accused_id": c.accused_id, "investigator_id": c.investigator_id,
        "ai_risk_assessment": c.ai_risk_assessment, "ai_recommended_actions": c.ai_recommended_actions or [],
        "opened_at": c.opened_at.isoformat() if c.opened_at else None,
    } for c in rows]


@router.post("/er-cases", status_code=201)
async def create_er_case(
    body: ERCaseCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    case = ERCase(
        tenant_id=tenant_id, title=body.title, description=body.description,
        reporter_id=body.reporter_id, accused_id=body.accused_id,
        category=body.category, severity=body.severity, status=CaseStatus.OPEN,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="er_case", resource_id=case.id)
    return {"id": case.id, "status": case.status.value}


@router.post("/er-cases/{case_id}/transition")
async def transition_er_case(
    case_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["er_case"], case_id, body.to_state, tenant, note=body.note)
    if body.to_state == "CLOSED":
        case = (await db.execute(select(ERCase).where(
            ERCase.id == case_id, ERCase.tenant_id == tenant["tenant_id"]))).scalar_one_or_none()
        if case:
            case.closed_at = datetime.now(timezone.utc)
            db.add(case)
            await db.commit()
    return result


@router.post("/er-cases/{case_id}/triage")
async def triage_er_case(
    case_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Employee Relations Agent's severity/risk triage through the
    gated 7-gate pipeline (EEOC + GDPR). Wires EmployeeRelationsAgent,
    previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    case = (await db.execute(select(ERCase).where(
        ERCase.id == case_id, ERCase.tenant_id == tenant_id))).scalar_one_or_none()
    if not case:
        raise HTTPException(404, "ER case not found")
    from app.hr.agents.employee_relations_agent import EmployeeRelationsAgent
    agent = EmployeeRelationsAgent()
    result = await agent.triage_case(db, case_id)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="er_case", resource_id=case_id,
        details={"status": result.get("status")})
    return {"case_id": case_id, **result}


# ── Workforce Planning ─────────────────────────────────────────────────────────

class HeadcountPlanCreate(BaseModel):
    name: str
    department_id: Optional[str] = None
    target_year: int = Field(..., ge=2020, le=2100)
    budget_allocated: float = 0.0
    currency: str = "USD"
    planned_positions: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/headcount-plans")
async def list_headcount_plans(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(HeadcountPlan).where(HeadcountPlan.tenant_id == tenant_id)
        .order_by(HeadcountPlan.target_year.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": p.id, "name": p.name, "department_id": p.department_id, "target_year": p.target_year,
        "budget_allocated": p.budget_allocated, "currency": p.currency,
        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
        "planned_positions": p.planned_positions or [],
    } for p in rows]


@router.post("/headcount-plans", status_code=201)
async def create_headcount_plan(
    body: HeadcountPlanCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    plan = HeadcountPlan(
        tenant_id=tenant_id, name=body.name, department_id=body.department_id, target_year=body.target_year,
        budget_allocated=body.budget_allocated, currency=body.currency, planned_positions=body.planned_positions,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="headcount_plan", resource_id=plan.id)
    return {"id": plan.id, "status": plan.status.value}


@router.post("/headcount-plans/{plan_id}/transition")
async def transition_headcount_plan(
    plan_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["headcount_plan"], plan_id, body.to_state, tenant, note=body.note)


# ── Payroll Processing ─────────────────────────────────────────────────────────

class PayrollRunCreate(BaseModel):
    period_start: _date
    period_end: _date
    pay_date: _date


@router.get("/payroll-runs")
async def list_payroll_runs(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(PayrollRun).where(PayrollRun.tenant_id == tenant_id)
        .order_by(PayrollRun.period_start.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": r.id, "period_start": r.period_start.isoformat() if r.period_start else None,
        "period_end": r.period_end.isoformat() if r.period_end else None,
        "pay_date": r.pay_date.isoformat() if r.pay_date else None,
        "status": r.status.value if hasattr(r.status, "value") else str(r.status),
        "total_gross": r.total_gross, "total_net": r.total_net, "total_taxes": r.total_taxes,
        "total_deductions": r.total_deductions, "ai_anomalies_detected": r.ai_anomalies_detected or [],
    } for r in rows]


@router.post("/payroll-runs", status_code=201)
async def create_payroll_run(
    body: PayrollRunCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    if body.period_end < body.period_start:
        raise HTTPException(422, "period_end must be on or after period_start")
    run = PayrollRun(tenant_id=tenant_id, period_start=body.period_start,
                     period_end=body.period_end, pay_date=body.pay_date)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="payroll_run", resource_id=run.id)
    return {"id": run.id, "status": run.status.value}


@router.post("/payroll-runs/{run_id}/transition")
async def transition_payroll_run(
    run_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["payroll_run"], run_id, body.to_state, tenant, note=body.note)


@router.post("/payroll-runs/{run_id}/generate-payslips")
async def generate_payslips(
    run_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Generate one payslip per active employee who has a current Compensation
    record, for this run. Idempotent — skips employees who already have a
    payslip for it. Gross pay is prorated from the employee's real current
    Compensation.base_amount over the run's period length; there is no
    tax-withholding engine, so taxes/deductions stay empty and net equals
    gross rather than presenting a guessed number as a real one."""
    tenant_id = tenant["tenant_id"]
    run = (await db.execute(select(PayrollRun).where(
        PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id))).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Payroll run not found")

    existing_emp_ids = set((await db.execute(
        select(Payslip.employee_id).where(Payslip.run_id == run_id)
    )).scalars().all())
    employees = (await db.execute(select(HREmployee).where(
        HREmployee.tenant_id == tenant_id, HREmployee.status != EmploymentStatus.TERMINATED,
    ))).scalars().all()

    period_days = max(1, (run.period_end - run.period_start).days + 1)
    created = skipped_no_comp = skipped_existing = 0
    total_gross = 0.0
    for emp in employees:
        if emp.id in existing_emp_ids:
            skipped_existing += 1
            continue
        comp = (await db.execute(select(Compensation).where(
            Compensation.tenant_id == tenant_id, Compensation.employee_id == emp.id,
            Compensation.is_current == True,
        ))).scalars().first()
        if not comp:
            skipped_no_comp += 1
            continue
        comp_type = comp.comp_type.value if hasattr(comp.comp_type, "value") else str(comp.comp_type)
        annual = comp.base_amount if comp_type == "SALARY" else comp.base_amount * 2080  # full-time hourly annualized
        gross = round(annual * (period_days / 365.0), 2)
        db.add(Payslip(tenant_id=tenant_id, run_id=run_id, employee_id=emp.id, gross_pay=gross, net_pay=gross))
        total_gross += gross
        created += 1

    if created:
        run.total_gross = round((run.total_gross or 0) + total_gross, 2)
        run.total_net = round((run.total_net or 0) + total_gross, 2)
        db.add(run)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="payroll_run", resource_id=run_id,
        details={"created": created, "skipped_no_compensation": skipped_no_comp, "skipped_existing": skipped_existing})
    return {"run_id": run_id, "created": created,
            "skipped_no_compensation": skipped_no_comp, "skipped_existing": skipped_existing}


@router.get("/payslips")
async def list_payslips(
    run_id: Optional[str] = None, employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(Payslip).where(Payslip.tenant_id == tenant_id)
    if run_id:
        stmt = stmt.where(Payslip.run_id == run_id)
    if employee_id:
        stmt = stmt.where(Payslip.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(Payslip.created_at.desc()).limit(200))).scalars().all()
    return [{
        "id": p.id, "run_id": p.run_id, "employee_id": p.employee_id,
        "gross_pay": p.gross_pay, "net_pay": p.net_pay, "taxes": p.taxes or {}, "deductions": p.deductions or {},
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in rows]


# ── Compliance & Reporting ─────────────────────────────────────────────────────

class ComplianceReportCreate(BaseModel):
    framework: str = Field(..., pattern="^(EEOC|OSHA|HIPAA|I9|GDPR|ACA)$")
    report_name: str
    period_year: int = Field(..., ge=2020, le=2100)
    data: Dict[str, Any] = Field(default_factory=dict)


@router.get("/compliance-reports")
async def list_compliance_reports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ComplianceReport).where(ComplianceReport.tenant_id == tenant_id)
        .order_by(ComplianceReport.generated_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": r.id, "framework": r.framework.value if hasattr(r.framework, "value") else str(r.framework),
        "report_name": r.report_name, "period_year": r.period_year, "status": r.status, "data": r.data or {},
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
    } for r in rows]


@router.post("/compliance-reports", status_code=201)
async def create_compliance_report(
    body: ComplianceReportCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    report = ComplianceReport(
        tenant_id=tenant_id, framework=body.framework, report_name=body.report_name,
        period_year=body.period_year, data=body.data,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="compliance_report", resource_id=report.id)
    return {"id": report.id, "framework": report.framework.value}


@router.post("/compliance-reports/eeoc/generate", status_code=201)
async def generate_eeoc_compliance_report(
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the real EEOC four-fifths disparate-impact test across every
    requisition's candidates tenant-wide and persist it as a ComplianceReport
    (plus a BLOCKER ComplianceViolation on any adverse-impact finding).
    Reuses the exact statistical test the per-requisition fairness sweep
    runs — never a fabricated compliance score."""
    tenant_id = tenant["tenant_id"]
    from app.hr.services.fairness_sweep import build_cohort_outcomes
    from app.services.disparate_impact import four_fifths_test

    built = await build_cohort_outcomes(db, tenant_id, requisition_id=None)
    test_result = four_fifths_test(built["cohorts"])
    year = datetime.now(timezone.utc).year
    report = ComplianceReport(
        tenant_id=tenant_id, framework="EEOC",
        report_name=f"EEO adverse-impact self-audit {year}", period_year=year,
        data={"decided_total": built["decided_total"], **test_result}, status="GENERATED",
    )
    db.add(report)
    if not test_result["passed"]:
        db.add(ComplianceViolation(
            tenant_id=tenant_id, framework="EEOC", severity="BLOCKER",
            description=f"Adverse impact detected on {', '.join(test_result['flagged'])} across the candidate "
                        "pool (four-fifths rule, statistically significant).",
            context=test_result, actor_id="hr_compliance_report_generator",
        ))
    await db.commit()
    await db.refresh(report)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="compliance_report", resource_id=report.id, details={"passed": test_result["passed"]})
    return {"id": report.id, "passed": test_result["passed"], "flagged": test_result["flagged"],
            "decided_total": built["decided_total"]}


class ViolationResolve(BaseModel):
    resolution_notes: str = Field(..., max_length=512)


@router.get("/compliance-violations")
async def list_compliance_violations(
    resolved: Optional[bool] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(ComplianceViolation).where(ComplianceViolation.tenant_id == tenant_id)
    if resolved is not None:
        stmt = stmt.where(ComplianceViolation.resolved == resolved)
    rows = (await db.execute(stmt.order_by(ComplianceViolation.created_at.desc()).limit(200))).scalars().all()
    return [{
        "id": v.id, "framework": v.framework, "severity": v.severity, "description": v.description,
        "resolved": v.resolved, "resolution_notes": v.resolution_notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in rows]


@router.post("/compliance-violations/{violation_id}/resolve")
async def resolve_compliance_violation(
    violation_id: str, body: ViolationResolve,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    v = (await db.execute(select(ComplianceViolation).where(
        ComplianceViolation.id == violation_id, ComplianceViolation.tenant_id == tenant_id))).scalar_one_or_none()
    if not v:
        raise HTTPException(404, "Violation not found")
    v.resolved = True
    v.resolution_notes = body.resolution_notes
    db.add(v)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="compliance_violation", resource_id=violation_id)
    return {"id": violation_id, "resolved": True}


# ── HR Analytics Snapshots ──────────────────────────────────────────────────────

@router.get("/hr-metrics")
async def list_hr_metrics(
    days: int = 180, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = (await db.execute(
        select(HRMetricSnapshot).where(
            HRMetricSnapshot.tenant_id == tenant_id, HRMetricSnapshot.snapshot_date >= cutoff,
        ).order_by(HRMetricSnapshot.snapshot_date.asc()).limit(400)
    )).scalars().all()
    return [{
        "id": s.id, "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
        "total_headcount": s.total_headcount, "active_contractors": s.active_contractors,
        "voluntary_turnover_ytd": s.voluntary_turnover_ytd, "involuntary_turnover_ytd": s.involuntary_turnover_ytd,
        "open_requisitions": s.open_requisitions, "time_to_fill_avg_days": s.time_to_fill_avg_days,
        "offer_acceptance_rate": s.offer_acceptance_rate, "diversity_metrics": s.diversity_metrics or {},
        "total_payroll_run_rate": s.total_payroll_run_rate,
    } for s in rows]


@router.post("/hr-metrics/snapshot", status_code=201)
async def generate_hr_metric_snapshot(
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Compute today's HR metric snapshot from real current rows (upserts if
    one already exists for today). Fields with no real data source (e.g.
    voluntary vs involuntary turnover split — HREmployee has no termination
    reason) stay null rather than a fabricated number."""
    tenant_id = tenant["tenant_id"]
    today = datetime.now(timezone.utc).date()

    emps = (await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id))).scalars().all()
    reqs = (await db.execute(select(JobRequisition).where(JobRequisition.tenant_id == tenant_id))).scalars().all()
    candidates = (await db.execute(select(Candidate).where(Candidate.tenant_id == tenant_id))).scalars().all()

    def _status(e): return e.status.value if hasattr(e.status, "value") else str(e.status)
    def _stage(c): return c.stage.value if hasattr(c.stage, "value") else str(c.stage)
    def _rstatus(r): return r.status.value if hasattr(r.status, "value") else str(r.status)

    active_contractors = sum(1 for e in emps if _status(e) == "CONTRACTOR")
    open_reqs = sum(1 for r in reqs if _rstatus(r) == "OPEN")
    hired = [c for c in candidates if _stage(c) == "HIRED"]
    offers_out = sum(1 for c in candidates if _stage(c) == "OFFER_EXTENDED")
    offer_acceptance_rate = round(len(hired) / (len(hired) + offers_out) * 100, 1) if (hired or offers_out) else None
    fill_days = [
        (c.updated_at - c.applied_at).days for c in hired
        if c.updated_at and c.applied_at and (c.updated_at - c.applied_at).days >= 0
    ]
    time_to_fill = round(sum(fill_days) / len(fill_days), 1) if fill_days else None

    latest_run = (await db.execute(
        select(PayrollRun).where(PayrollRun.tenant_id == tenant_id).order_by(PayrollRun.period_end.desc())
    )).scalars().first()
    payroll_run_rate = latest_run.total_gross if latest_run and latest_run.total_gross else None

    existing = (await db.execute(select(HRMetricSnapshot).where(
        HRMetricSnapshot.tenant_id == tenant_id, HRMetricSnapshot.snapshot_date == today,
    ))).scalar_one_or_none()
    snap = existing or HRMetricSnapshot(tenant_id=tenant_id, snapshot_date=today)
    snap.total_headcount = len(emps)
    snap.active_contractors = active_contractors
    snap.open_requisitions = open_reqs
    snap.offer_acceptance_rate = offer_acceptance_rate
    snap.time_to_fill_avg_days = time_to_fill
    snap.total_payroll_run_rate = payroll_run_rate
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return {"id": snap.id, "snapshot_date": snap.snapshot_date.isoformat(), "total_headcount": snap.total_headcount}


# ── Interviews (Recruiting) ────────────────────────────────────────────────────

class InterviewCreate(BaseModel):
    candidate_id: str
    interviewer_id: str
    scheduled_at: datetime
    duration_mins: int = Field(60, gt=0)
    interview_type: str = Field(..., max_length=64)


@router.get("/interviews")
async def list_interviews(
    candidate_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(Interview).where(Interview.tenant_id == tenant_id)
    if candidate_id:
        stmt = stmt.where(Interview.candidate_id == candidate_id)
    rows = (await db.execute(stmt.order_by(Interview.scheduled_at.desc()).limit(200))).scalars().all()
    return [{
        "id": i.id, "candidate_id": i.candidate_id, "interviewer_id": i.interviewer_id,
        "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
        "duration_mins": i.duration_mins, "interview_type": i.interview_type,
        "feedback_submitted": i.feedback_submitted, "score": i.score, "recommendation": i.recommendation,
        "notes": i.notes,
    } for i in rows]


@router.post("/interviews", status_code=201)
async def schedule_interview(
    body: InterviewCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    cand = (await db.execute(select(Candidate).where(
        Candidate.id == body.candidate_id, Candidate.tenant_id == tenant_id))).scalar_one_or_none()
    if not cand:
        raise HTTPException(404, "Candidate not found")
    interviewer = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.interviewer_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not interviewer:
        raise HTTPException(404, "Interviewer not found")
    interview = Interview(
        tenant_id=tenant_id, candidate_id=body.candidate_id, interviewer_id=body.interviewer_id,
        scheduled_at=body.scheduled_at, duration_mins=body.duration_mins, interview_type=body.interview_type,
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="interview", resource_id=interview.id)
    return {"id": interview.id, "scheduled_at": interview.scheduled_at.isoformat()}


class InterviewFeedback(BaseModel):
    score: int = Field(..., ge=1, le=5)
    recommendation: str = Field(..., pattern="^(STRONG_HIRE|HIRE|NO_HIRE|STRONG_NO_HIRE)$")
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/interviews/{interview_id}/feedback")
async def submit_interview_feedback(
    interview_id: str, body: InterviewFeedback,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    interview = (await db.execute(select(Interview).where(
        Interview.id == interview_id, Interview.tenant_id == tenant_id))).scalar_one_or_none()
    if not interview:
        raise HTTPException(404, "Interview not found")
    interview.score = body.score
    interview.recommendation = body.recommendation
    interview.notes = body.notes
    interview.feedback_submitted = True
    db.add(interview)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="interview", resource_id=interview_id)
    return {"id": interview_id, "feedback_submitted": True, "recommendation": interview.recommendation}


# ── Employee Documents ─────────────────────────────────────────────────────────

class EmployeeDocumentCreate(BaseModel):
    employee_id: str
    doc_type: str = Field(..., pattern="^(I9|W4|OFFER_LETTER|HANDBOOK_ACK|PERFORMANCE_REVIEW|DISCIPLINARY|OTHER)$")
    title: str
    file_path: str
    is_pii: bool = True
    expiration_date: Optional[_date] = None


@router.get("/employee-documents")
async def list_employee_documents(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(EmployeeDocument).where(EmployeeDocument.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(EmployeeDocument.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(EmployeeDocument.uploaded_at.desc()).limit(200))).scalars().all()
    return [{
        "id": d.id, "employee_id": d.employee_id,
        "doc_type": d.doc_type.value if hasattr(d.doc_type, "value") else str(d.doc_type),
        "title": d.title, "is_signed": d.is_signed,
        "signature_date": d.signature_date.isoformat() if d.signature_date else None,
        "expiration_date": d.expiration_date.isoformat() if d.expiration_date else None,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
    } for d in rows]


@router.post("/employee-documents", status_code=201)
async def create_employee_document(
    body: EmployeeDocumentCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    doc = EmployeeDocument(
        tenant_id=tenant_id, employee_id=body.employee_id, doc_type=body.doc_type, title=body.title,
        file_path=body.file_path, is_pii=body.is_pii, expiration_date=body.expiration_date,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="employee_document", resource_id=doc.id)
    return {"id": doc.id, "title": doc.title}


@router.post("/employee-documents/{document_id}/sign")
async def sign_employee_document(
    document_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    doc = (await db.execute(select(EmployeeDocument).where(
        EmployeeDocument.id == document_id, EmployeeDocument.tenant_id == tenant_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.is_signed = True
    doc.signature_date = datetime.now(timezone.utc)
    db.add(doc)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="employee_document", resource_id=document_id)
    return {"id": document_id, "is_signed": True}


# ── Timesheets ──────────────────────────────────────────────────────────────────

class TimesheetCreate(BaseModel):
    employee_id: str
    period_start: _date
    period_end: _date
    total_regular_hours: float = Field(0.0, ge=0)
    total_overtime_hours: float = Field(0.0, ge=0)


@router.get("/timesheets")
async def list_timesheets(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(Timesheet).where(Timesheet.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(Timesheet.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(Timesheet.period_start.desc()).limit(200))).scalars().all()
    return [{
        "id": t.id, "employee_id": t.employee_id,
        "period_start": t.period_start.isoformat() if t.period_start else None,
        "period_end": t.period_end.isoformat() if t.period_end else None,
        "total_regular_hours": t.total_regular_hours, "total_overtime_hours": t.total_overtime_hours,
        "status": t.status,
    } for t in rows]


@router.post("/timesheets", status_code=201)
async def create_timesheet(
    body: TimesheetCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    if body.period_end < body.period_start:
        raise HTTPException(422, "period_end must be on or after period_start")
    ts = Timesheet(
        tenant_id=tenant_id, employee_id=body.employee_id, period_start=body.period_start,
        period_end=body.period_end, total_regular_hours=body.total_regular_hours,
        total_overtime_hours=body.total_overtime_hours,
    )
    db.add(ts)
    await db.commit()
    await db.refresh(ts)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="timesheet", resource_id=ts.id)
    return {"id": ts.id, "status": ts.status}


@router.post("/timesheets/{timesheet_id}/transition")
async def transition_timesheet(
    timesheet_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["timesheet"], timesheet_id, body.to_state, tenant, note=body.note)


# ── Performance Reviews: cycles, creation, ratings, AI synthesis ───────────────

class ReviewCycleCreate(BaseModel):
    name: str
    start_date: datetime
    end_date: datetime


@router.get("/performance-cycles")
async def list_performance_cycles(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ReviewCycle).where(ReviewCycle.tenant_id == tenant_id)
        .order_by(ReviewCycle.start_date.desc()).limit(100)
    )).scalars().all()
    return [{
        "id": c.id, "name": c.name, "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None, "is_active": c.is_active,
    } for c in rows]


@router.post("/performance-cycles", status_code=201)
async def create_performance_cycle(
    body: ReviewCycleCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    cycle = ReviewCycle(tenant_id=tenant_id, name=body.name, start_date=body.start_date, end_date=body.end_date)
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"), resource_type="review_cycle", resource_id=cycle.id)
    return {"id": cycle.id, "name": cycle.name}


class PerformanceReviewCreate(BaseModel):
    cycle_id: str
    employee_id: str
    reviewer_id: str


@router.post("/performance-reviews", status_code=201)
async def create_performance_review(
    body: PerformanceReviewCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    cycle = (await db.execute(select(ReviewCycle).where(
        ReviewCycle.id == body.cycle_id, ReviewCycle.tenant_id == tenant_id))).scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "Review cycle not found")
    emp = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.employee_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Employee not found")
    reviewer = (await db.execute(select(HREmployee).where(
        HREmployee.id == body.reviewer_id, HREmployee.tenant_id == tenant_id))).scalar_one_or_none()
    if not reviewer:
        raise HTTPException(404, "Reviewer not found")
    review = PerformanceReview(
        tenant_id=tenant_id, cycle_id=body.cycle_id, employee_id=body.employee_id,
        reviewer_id=body.reviewer_id, status="DRAFT",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review.id)
    return {"id": review.id, "status": review.status}


@router.post("/performance-reviews/{review_id}/transition")
async def transition_performance_review(
    review_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Only DRAFT -> PENDING_EMPLOYEE moves through the generic engine; the
    two steps after that always carry a rating payload, so they go through
    the self-rating/manager-rating endpoints instead (see WORKFLOW_SPECS)."""
    return await apply_transition(db, WORKFLOW_SPECS["performance_review"], review_id,
                                  body.to_state, tenant, note=body.note)


class RatingSubmit(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    assessment: str = Field(..., max_length=4000)


@router.post("/performance-reviews/{review_id}/self-rating")
async def submit_self_rating(
    review_id: str, body: RatingSubmit,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    review = (await db.execute(select(PerformanceReview).where(
        PerformanceReview.id == review_id, PerformanceReview.tenant_id == tenant_id))).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Performance review not found")
    if review.status not in ("DRAFT", "PENDING_EMPLOYEE"):
        raise HTTPException(409, detail={"error": "invalid_transition", "from_state": review.status,
                                          "reason": "Self-rating can only be submitted from DRAFT or PENDING_EMPLOYEE."})
    from_state = review.status
    review.self_rating = body.rating
    review.self_assessment = body.assessment
    review.status = "PENDING_MANAGER"
    db.add(review)
    db.add(_workflow_event(tenant_id, "performance_review", review_id, from_state, "PENDING_MANAGER", tenant))
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"id": review_id, "status": review.status}


@router.post("/performance-reviews/{review_id}/manager-rating")
async def submit_manager_rating(
    review_id: str, body: RatingSubmit,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    review = (await db.execute(select(PerformanceReview).where(
        PerformanceReview.id == review_id, PerformanceReview.tenant_id == tenant_id))).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Performance review not found")
    if review.status != "PENDING_MANAGER":
        raise HTTPException(409, detail={"error": "invalid_transition", "from_state": review.status,
                                          "reason": "Manager rating can only be submitted from PENDING_MANAGER."})
    from_state = review.status
    review.manager_rating = body.rating
    review.manager_assessment = body.assessment
    review.status = "COMPLETED"
    db.add(review)
    db.add(_workflow_event(tenant_id, "performance_review", review_id, from_state, "COMPLETED", tenant))
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"id": review_id, "status": review.status}


class SynthesizeFeedbackBody(BaseModel):
    raw_feedback: List[str] = Field(..., min_length=1)


@router.post("/performance-reviews/{review_id}/synthesize-feedback")
async def synthesize_review_feedback(
    review_id: str, body: SynthesizeFeedbackBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Performance Agent's 360-feedback synthesis, which persists
    ai_feedback_summary/ai_growth_areas directly onto the review. Wires
    PerformanceAgent, previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    review = (await db.execute(select(PerformanceReview).where(
        PerformanceReview.id == review_id, PerformanceReview.tenant_id == tenant_id))).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Performance review not found")
    from app.hr.agents.performance_agent import PerformanceAgent
    agent = PerformanceAgent()
    analysis = await agent.synthesize_feedback(db, review_id, body.raw_feedback)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"review_id": review_id, "analysis": analysis}


# ── BambooHR Connector ─────────────────────────────────────────────────────────

class BambooHRSyncBody(BaseModel):
    subdomain: str = Field(..., min_length=1, max_length=64)
    api_key: str = Field(..., min_length=1, max_length=256)


@router.post("/connectors/bamboohr/sync")
async def sync_bamboohr(
    body: BambooHRSyncBody, tenant: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    """Pull the BambooHR employee directory and upsert it into hr_employees.
    Credentials travel in this request only — nothing is persisted (see
    app/hr/connectors/bamboohr.py:sync_employees; there is no connector
    credential store for HR yet). Admin-only: this both reads and writes
    employee PII. Wires BambooHRConnector, previously never instantiated."""
    from app.hr.connectors.bamboohr import sync_employees
    tenant_id = tenant["tenant_id"]
    result = await sync_employees(db, tenant_id, body.subdomain, body.api_key)
    if not result.get("ok"):
        raise HTTPException(502, detail=result.get("error") or "BambooHR sync failed")
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="hr_connector", resource_id="bamboohr",
        details={"created": result.get("created"), "updated": result.get("updated")})
    return result
