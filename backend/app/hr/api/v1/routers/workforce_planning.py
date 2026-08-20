"""KAEOS HR V1 — workforce planning

Workforce planning: headcount plans and their approval workflow.
"""
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.models.workforce_planning import HeadcountPlan
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


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
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="headcount_plan", resource_id=plan.id)
    return {"id": plan.id, "status": plan.status.value}


@router.post("/headcount-plans/{plan_id}/transition")
async def transition_headcount_plan(
    plan_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["headcount_plan"], plan_id, body.to_state, tenant, note=body.note)
