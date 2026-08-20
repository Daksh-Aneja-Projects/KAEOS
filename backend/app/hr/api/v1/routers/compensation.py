"""KAEOS HR V1 — compensation

Compensation and equity records plus the gated market-band analysis.
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
from app.hr.api.v1.routers._shared import _exec_id
from app.hr.models.compensation import Compensation
from app.hr.models.core import HREmployee

router = APIRouter()


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
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
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
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="compensation", resource_id=comp.id)
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
    comp = await get_or_404(db, Compensation, compensation_id, tenant_id, detail="Compensation record not found")
    # REVIEW: this is the ONE fetch-or-404 in the ten department routers with no
    # tenant_id predicate, so it is left hand-written rather than routed through
    # get_or_404() (which requires one). Reachable rows are still tenant-scoped in
    # practice - comp came from a tenant-filtered read and RLS covers the session -
    # but the query itself is unscoped, so the belt-and-braces filter every sibling
    # carries is missing here. The fix is `HREmployee.tenant_id == tenant_id` as a
    # second predicate; it changes the emitted SQL, so it is quarantined, not done here.
    emp = (await db.execute(select(HREmployee).where(HREmployee.id == comp.employee_id))).scalar_one_or_none()
    if not emp:
        raise HTTPException(404, "Linked employee not found")

    from app.hr.agents.compensation_agent import CompensationAgent
    from app.hr.agents.gated_runner import extract_decision
    agent = CompensationAgent()
    # ponytail: Compensation stores a single point value, not a band, so a
    # +/-10% envelope around the real current pay stands in for "current
    # band" here — upgrade to real min/max columns if banded comp is modeled.
    _base = float(comp.base_amount)  # a display band, not stored money -> float math is fine
    current_band = {"min": round(_base * 0.9, 2), "max": round(_base * 1.1, 2)}
    # Through the 7-gate pipeline (not the ungated agent method): only trust the
    # decision when the run cleared every gate.
    result = await agent.execute_via_pipeline(db, tenant_id, {
        "action": "analyze_salary_band",
        "job_title": emp.job_title, "location": emp.location or "Remote",
        "current_band": current_band,
    })
    status = result.get("status")
    analysis = extract_decision(result) if status == "SUCCESS_CLEAN" else {}

    reasoning = str(analysis.get("reasoning") or "")[:100]
    if reasoning:
        comp.change_reason = f"AI market analysis: {reasoning}"
        db.add(comp)
        await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="compensation", resource_id=compensation_id,
        details={"is_competitive": analysis.get("is_competitive"), "status": status})
    return {"compensation_id": compensation_id, "status": status, "analysis": analysis, "execution_id": _exec_id(result)}
