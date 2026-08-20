"""KAEOS HR V1 — payroll

Payroll runs, payslip generation and payslip reads.
"""
from decimal import Decimal
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.models.compensation import Compensation
from app.hr.models.core import HREmployee, EmploymentStatus
from app.hr.models.payroll import PayrollRun, Payslip
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


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
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="payroll_run", resource_id=run.id)
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
    run = await get_or_404(db, PayrollRun, run_id, tenant_id, detail="Payroll run not found")

    existing_emp_ids = set((await db.execute(
        select(Payslip.employee_id).where(Payslip.run_id == run_id)
    )).scalars().all())
    employees = (await db.execute(select(HREmployee).where(
        HREmployee.tenant_id == tenant_id, HREmployee.status != EmploymentStatus.TERMINATED,
    ))).scalars().all()

    # One batched current-compensation lookup instead of one SELECT per
    # employee (the old N+1). No match still means "no comp on file".
    # The old per-employee query was `.first()` on an unordered SELECT, so it
    # was already nondeterministic when an employee has two is_current rows
    # (reachable via a race on the demote loop above). Ordering newest-effective
    # first and keeping the first row seen makes the batch deterministic instead
    # of widening that window: single-row employees are unaffected.
    comp_by_employee: dict = {}
    for c in (await db.execute(select(Compensation).where(
        Compensation.tenant_id == tenant_id, Compensation.is_current == True,
    ).order_by(Compensation.effective_date.desc(), Compensation.id))).scalars().all():
        comp_by_employee.setdefault(c.employee_id, c)

    period_days = max(1, (run.period_end - run.period_start).days + 1)
    created = skipped_no_comp = skipped_existing = 0
    total_gross = Decimal("0")
    for emp in employees:
        if emp.id in existing_emp_ids:
            skipped_existing += 1
            continue
        comp = comp_by_employee.get(emp.id)
        if not comp:
            skipped_no_comp += 1
            continue
        comp_type = comp.comp_type.value if hasattr(comp.comp_type, "value") else str(comp.comp_type)
        annual = comp.base_amount if comp_type == "SALARY" else comp.base_amount * 2080  # full-time hourly annualized
        # gross is stored to Payslip.gross_pay (Numeric), so keep it exact Decimal.
        gross = round(annual * Decimal(period_days) / Decimal(365), 2)
        db.add(Payslip(tenant_id=tenant_id, run_id=run_id, employee_id=emp.id, gross_pay=gross, net_pay=gross))
        total_gross += gross
        created += 1

    if created:
        run.total_gross = round((run.total_gross or 0) + total_gross, 2)
        run.total_net = round((run.total_net or 0) + total_gross, 2)
        db.add(run)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="payroll_run", resource_id=run_id,
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
