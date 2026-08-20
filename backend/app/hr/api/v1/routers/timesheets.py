"""KAEOS HR V1 — timesheets

Timesheets and their approval workflow.
"""
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.models.core import HREmployee
from app.hr.models.time_attendance import Timesheet
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


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
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
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
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="timesheet", resource_id=ts.id)
    return {"id": ts.id, "status": ts.status}


@router.post("/timesheets/{timesheet_id}/transition")
async def transition_timesheet(
    timesheet_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    return await apply_transition(db, WORKFLOW_SPECS["timesheet"], timesheet_id, body.to_state, tenant, note=body.note)
