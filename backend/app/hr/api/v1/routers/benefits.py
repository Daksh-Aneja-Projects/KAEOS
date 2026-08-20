"""KAEOS HR V1 — benefits

Benefits administration: plans, enrollments and the gated eligibility
verification run.
"""
from datetime import date as _date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.api.v1.routers._shared import _exec_id
from app.hr.models.benefits import BenefitPlan, BenefitEnrollment, EnrollmentStatus as BenefitEnrollmentStatus
from app.hr.models.core import HREmployee
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS
from app.models.execution_status import ExecutionStatus

router = APIRouter()


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
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="benefit_plan", resource_id=plan.id)
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
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
    await get_or_404(db, BenefitPlan, body.plan_id, tenant_id, detail="Benefit plan not found")
    enrollment = BenefitEnrollment(
        tenant_id=tenant_id, employee_id=body.employee_id, plan_id=body.plan_id,
        coverage_level=body.coverage_level, effective_date=body.effective_date,
        covered_dependents=body.covered_dependents, status=BenefitEnrollmentStatus.PENDING,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
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
    enrollment = await get_or_404(db, BenefitEnrollment, enrollment_id, tenant_id, detail="Enrollment not found")
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
    verified = status == ExecutionStatus.SUCCESS_CLEAN
    if verified:
        enrollment.agent_verified = True
        current_status = enrollment.status.value if hasattr(enrollment.status, "value") else str(enrollment.status)
        if current_status == "PENDING":
            enrollment.status = BenefitEnrollmentStatus.ACTIVE
        db.add(enrollment)
        await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="benefit_enrollment", resource_id=enrollment_id,
        details={"verified": verified, "status": status})
    return {"enrollment_id": enrollment_id, "verified": verified, "status": status, "execution_id": _exec_id(result)}
