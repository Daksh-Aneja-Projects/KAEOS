"""KAEOS HR V1 — workflows

The shared workflow layer (generated from app.core.department_endpoints)
plus the two hand-written single-entity transitions and time-off creation
that sit between the two generated mounts.

The two ``make_department_workflow_router`` mounts stay at these exact
points in the route order, as they did in the pre-split router: the
factory's docstring calls that out as the reason it mounts selectively.
"""
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import make_department_workflow_router
from app.core.tenant import approver_identity, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.models.core import HREmployee
from app.hr.models.time_attendance import TimeOffRequest
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════


# Generated from the shared factory in app/core/department_endpoints.py.
# Endpoint names and docstrings are the hand-written originals, so the
# operationIds and descriptions in the OpenAPI schema are unchanged.
router.include_router(make_department_workflow_router(
    "hr", WORKFLOW_SPECS,
    workflows_doc='Declared state machines — candidate stages stay on /candidates/{id}/advance.',
    events_doc='Tenant-scoped transition audit trail for HR entities.',
))


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
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="time_off_request", resource_id=req.id,
    )
    return {"id": req.id, "employee_id": req.employee_id,
            "status": req.status.value if hasattr(req.status, "value") else str(req.status),
            "leave_type": req.leave_type.value if hasattr(req.leave_type, "value") else str(req.leave_type),
            "hours_requested": req.hours_requested}


router.include_router(make_department_workflow_router(
    "hr", WORKFLOW_SPECS,
    bulk_doc='Apply one transition to up to 200 hr entities; per-id outcomes.',
))
