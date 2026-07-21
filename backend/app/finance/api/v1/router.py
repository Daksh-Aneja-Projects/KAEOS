"""
KAEOS Finance Domain — V1 API Router
Comprehensive CRUD and operational endpoints for all finance functions.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.finance.models.core import ChartOfAccount
from app.finance.models.accounts_payable import Vendor, Invoice, Payment, InvoiceStatus
from app.finance.models.accounts_receivable import Customer, CustomerInvoice, CustomerInvoiceStatus
from app.finance.models.budgeting import Budget, BudgetLine, Forecast, BudgetStatus
from app.finance.models.expense import ExpenseReport, ExpenseItem, ExpenseReportStatus
from app.finance.models.treasury import BankAccount, CashFlow
from app.finance.models.tax import TaxFiling, TaxRule
from app.finance.models.reporting import FinancialReport
from app.finance.models.audit import AuditFinding
from app.finance.models.compliance import FinanceComplianceRule, SOXControl

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/finance", tags=["Finance"])


# ═══════════════════════════════════════════════════════════════════════
# Dashboard / Overview
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def finance_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Aggregated finance dashboard KPIs."""
    # Vendors
    vendor_q = await db.execute(select(sqlfunc.count()).select_from(Vendor).where(Vendor.tenant_id == tenant_id))
    total_vendors = vendor_q.scalar() or 0

    # AP
    ap_q = await db.execute(
        select(sqlfunc.count(), sqlfunc.coalesce(sqlfunc.sum(Invoice.balance_due), 0))
        .select_from(Invoice).where(Invoice.tenant_id == tenant_id)
        .where(Invoice.status.in_([InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.APPROVED, InvoiceStatus.OVERDUE]))
    )
    ap_row = ap_q.one()
    open_invoices, total_ap = int(ap_row[0] or 0), float(ap_row[1] or 0)

    # AR
    ar_q = await db.execute(
        select(sqlfunc.count(), sqlfunc.coalesce(sqlfunc.sum(CustomerInvoice.balance_due), 0))
        .select_from(CustomerInvoice).where(CustomerInvoice.tenant_id == tenant_id)
        .where(CustomerInvoice.status.in_([CustomerInvoiceStatus.SENT, CustomerInvoiceStatus.OVERDUE, CustomerInvoiceStatus.PARTIALLY_PAID]))
    )
    ar_row = ar_q.one()
    open_receivables, total_ar = int(ar_row[0] or 0), float(ar_row[1] or 0)

    # Bank balance
    bank_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(BankAccount.current_balance), 0))
        .select_from(BankAccount).where(BankAccount.tenant_id == tenant_id).where(BankAccount.is_active == True)
    )
    total_cash = float(bank_q.scalar() or 0)

    # Expense reports
    exp_q = await db.execute(
        select(sqlfunc.count()).select_from(ExpenseReport).where(ExpenseReport.tenant_id == tenant_id)
        .where(ExpenseReport.status == ExpenseReportStatus.PENDING_APPROVAL)
    )
    pending_expenses = exp_q.scalar() or 0

    # Budget
    budget_q = await db.execute(
        select(Budget).where(Budget.tenant_id == tenant_id).where(Budget.status == BudgetStatus.ACTIVE)
    )
    active_budgets = budget_q.scalars().all()

    # Audit findings
    finding_q = await db.execute(
        select(sqlfunc.count()).select_from(AuditFinding).where(AuditFinding.tenant_id == tenant_id)
        .where(AuditFinding.status.in_(["OPEN", "IN_PROGRESS"]))
    )
    open_findings = finding_q.scalar() or 0

    return {
        "total_cash_position": total_cash,
        "accounts_payable": {"open_invoices": open_invoices, "total_outstanding": total_ap},
        "accounts_receivable": {"open_receivables": open_receivables, "total_outstanding": total_ar},
        "total_vendors": total_vendors,
        "pending_expense_reports": pending_expenses,
        "active_budgets": len(active_budgets),
        "budget_variance_pct": active_budgets[0].variance_pct if active_budgets else None,
        "open_audit_findings": open_findings,
        "net_working_capital": total_cash + total_ar - total_ap,
    }


# ═══════════════════════════════════════════════════════════════════════
# Chart of Accounts
# ═══════════════════════════════════════════════════════════════════════

@router.get("/chart-of-accounts")
async def list_chart_of_accounts(tenant_id: str = Depends(get_tenant_id), account_type: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id)
    if account_type:
        q = q.where(ChartOfAccount.account_type == account_type)
    result = await db.execute(q.order_by(ChartOfAccount.account_code).limit(200))
    accounts = result.scalars().all()
    return [{"id": a.id, "code": a.account_code, "name": a.account_name, "type": a.account_type.value,
             "balance": float(a.current_balance or 0), "currency": a.currency, "is_active": a.is_active,
             "department": a.department, "cost_center": a.cost_center} for a in accounts]


# ═══════════════════════════════════════════════════════════════════════
# Accounts Payable
# ═══════════════════════════════════════════════════════════════════════

@router.get("/vendors")
async def list_vendors(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Vendor).where(Vendor.tenant_id == tenant_id)
    if status:
        q = q.where(Vendor.status == status)
    result = await db.execute(q.limit(200))
    vendors = result.scalars().all()
    return [{"id": v.id, "code": v.vendor_code, "name": v.name, "status": v.status.value,
             "payment_terms": v.payment_terms_days, "spend_ytd": float(v.total_spend_ytd or 0),
             "performance_score": v.performance_score, "risk_level": v.risk_level} for v in vendors]

@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant_id))
    v = q.scalar_one_or_none()
    if not v:
        # 404 (not 403) for another tenant's row: 403 would confirm the id exists.
        raise HTTPException(404, "Vendor not found")
    return {"id": v.id, "code": v.vendor_code, "name": v.name, "legal_name": v.legal_name,
            "email": v.email, "phone": v.phone, "status": v.status.value, "payment_terms": v.payment_terms_days,
            "currency": v.currency, "w9_on_file": v.w9_on_file, "risk_level": v.risk_level,
            "spend_ytd": float(v.total_spend_ytd or 0), "invoices_ytd": v.total_invoices_ytd,
            "performance_score": v.performance_score, "address": {"line1": v.address_line1, "city": v.city, "state": v.state, "country": v.country}}

@router.get("/invoices")
async def list_invoices(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, vendor_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if status:
        q = q.where(Invoice.status == status)
    if vendor_id:
        q = q.where(Invoice.vendor_id == vendor_id)
    result = await db.execute(q.order_by(Invoice.due_date).limit(200))
    invoices = result.scalars().all()
    return [{"id": i.id, "number": i.invoice_number, "vendor_id": i.vendor_id, "status": i.status.value,
             "total": float(i.total_amount), "balance": float(i.balance_due), "due_date": str(i.due_date),
             "po_number": i.po_number, "three_way_match": i.three_way_match_status, "ai_duplicate": i.ai_duplicate_flag} for i in invoices]

@router.get("/payments")
async def list_payments(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Payment).where(Payment.tenant_id == tenant_id).order_by(Payment.payment_date.desc()).limit(200))
    payments = q.scalars().all()
    return [{"id": p.id, "number": p.payment_number, "vendor_id": p.vendor_id, "amount": float(p.amount),
             "method": p.method.value, "status": p.status.value, "date": str(p.payment_date)} for p in payments]


# ═══════════════════════════════════════════════════════════════════════
# Accounts Receivable
# ═══════════════════════════════════════════════════════════════════════

@router.get("/customers")
async def list_customers(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Customer).where(Customer.tenant_id == tenant_id).limit(200))
    customers = q.scalars().all()
    return [{"id": c.id, "code": c.customer_code, "name": c.name, "status": c.status.value,
             "outstanding": float(c.total_outstanding or 0), "revenue_ytd": float(c.total_revenue_ytd or 0),
             "dso": c.days_sales_outstanding, "churn_risk": c.ai_churn_risk,
             "aging": {"current": float(c.aging_current or 0), "30": float(c.aging_30 or 0),
                       "60": float(c.aging_60 or 0), "90": float(c.aging_90 or 0), "over_90": float(c.aging_over_90 or 0)}}
            for c in customers]

@router.get("/receivables")
async def list_receivables(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(CustomerInvoice).where(CustomerInvoice.tenant_id == tenant_id)
    if status:
        q = q.where(CustomerInvoice.status == status)
    result = await db.execute(q.order_by(CustomerInvoice.due_date).limit(200))
    invoices = result.scalars().all()
    return [{"id": i.id, "number": i.invoice_number, "customer_id": i.customer_id, "status": i.status.value,
             "total": float(i.total_amount), "balance": float(i.balance_due), "due_date": str(i.due_date),
             "dunning_level": i.dunning_level} for i in invoices]


# ═══════════════════════════════════════════════════════════════════════
# Budgets & Forecasts
# ═══════════════════════════════════════════════════════════════════════

@router.get("/budgets")
async def list_budgets(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Budget).where(Budget.tenant_id == tenant_id).limit(200))
    budgets = q.scalars().all()
    return [{"id": b.id, "name": b.name, "type": b.budget_type, "year": b.fiscal_year, "status": b.status.value,
             "planned": float(b.total_planned), "actual": float(b.total_actual), "variance": float(b.total_variance),
             "variance_pct": b.variance_pct, "department": b.department} for b in budgets]

@router.get("/budgets/{budget_id}/lines")
async def get_budget_lines(budget_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # IDOR: this took no tenant at all - any caller who knew (or guessed) a
    # budget id got another company's financial lines back.
    q = await db.execute(
        select(BudgetLine)
        .where(BudgetLine.tenant_id == tenant_id, BudgetLine.budget_id == budget_id)
        .order_by(BudgetLine.period)
        .limit(200)
    )
    lines = q.scalars().all()
    return [{"id": l.id, "category": l.category, "period": l.period, "label": l.period_label,
             "planned": float(l.planned_amount), "actual": float(l.actual_amount),
             "committed": float(l.committed_amount), "variance": float(l.variance)} for l in lines]

@router.get("/forecasts")
async def list_forecasts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Forecast).where(Forecast.tenant_id == tenant_id).limit(200))
    forecasts = q.scalars().all()
    return [{"id": f.id, "name": f.forecast_name, "type": f.forecast_type, "scenario": f.scenario,
             "total": float(f.total_forecast), "confidence": f.confidence_score,
             "period": f"{f.period_start} to {f.period_end}"} for f in forecasts]


# ═══════════════════════════════════════════════════════════════════════
# Expense Management
# ═══════════════════════════════════════════════════════════════════════

@router.get("/expense-reports")
async def list_expense_reports(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ExpenseReport).where(ExpenseReport.tenant_id == tenant_id)
    if status:
        q = q.where(ExpenseReport.status == status)
    result = await db.execute(q.order_by(ExpenseReport.created_at.desc()).limit(200))
    reports = result.scalars().all()
    return [{"id": r.id, "number": r.report_number, "title": r.title, "employee_id": r.employee_id,
             "status": r.status.value, "total": float(r.total_amount), "approved": float(r.approved_amount or 0),
             "compliance_score": r.ai_compliance_score, "violations": len(r.ai_policy_violations or [])} for r in reports]

@router.get("/expense-reports/{report_id}/items")
async def get_expense_items(report_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(ExpenseItem)
        .where(ExpenseItem.tenant_id == tenant_id, ExpenseItem.report_id == report_id)
        .order_by(ExpenseItem.line_number)
        .limit(200)
    )
    items = q.scalars().all()
    return [{"id": i.id, "date": str(i.expense_date), "category": i.category.value, "description": i.description,
             "merchant": i.merchant, "amount": float(i.amount), "has_receipt": bool(i.receipt_path),
             "within_policy": i.is_within_policy, "billable": i.is_billable} for i in items]


# ═══════════════════════════════════════════════════════════════════════
# Treasury / Cash Management
# ═══════════════════════════════════════════════════════════════════════

@router.get("/bank-accounts")
async def list_bank_accounts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(BankAccount).where(BankAccount.tenant_id == tenant_id).limit(200))
    accounts = q.scalars().all()
    return [{"id": a.id, "name": a.account_name, "bank": a.bank_name, "masked_number": a.account_number_masked,
             "classification": a.classification.value, "balance": float(a.current_balance or 0),
             "available": float(a.available_balance or 0), "currency": a.currency,
             "last_reconciled": str(a.last_reconciled_date) if a.last_reconciled_date else None} for a in accounts]

@router.get("/cash-flow")
async def get_cash_flow(tenant_id: str = Depends(get_tenant_id), fiscal_year: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    q = select(CashFlow).where(CashFlow.tenant_id == tenant_id)
    if fiscal_year:
        q = q.where(CashFlow.fiscal_year == fiscal_year)
    result = await db.execute(q.order_by(CashFlow.flow_date.desc()).limit(200))
    flows = result.scalars().all()
    return [{"id": f.id, "date": str(f.flow_date), "type": f.flow_type.value, "category": f.category,
             "amount": float(f.amount), "is_forecast": f.is_forecast, "source": f.source_module} for f in flows]


# ═══════════════════════════════════════════════════════════════════════
# Tax
# ═══════════════════════════════════════════════════════════════════════

@router.get("/tax/filings")
async def list_tax_filings(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TaxFiling).where(TaxFiling.tenant_id == tenant_id).order_by(TaxFiling.due_date).limit(200))
    filings = q.scalars().all()
    return [{"id": f.id, "type": f.filing_type, "jurisdiction": f.jurisdiction, "period": f.period,
             "status": f.status.value, "liability": float(f.tax_liability or 0), "paid": float(f.tax_paid or 0),
             "due_date": str(f.due_date), "form": f.form_number} for f in filings]

@router.get("/tax/rules")
async def list_tax_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TaxRule).where(TaxRule.tenant_id == tenant_id).where(TaxRule.is_active == True).limit(200))
    rules = q.scalars().all()
    return [{"id": r.id, "name": r.name, "type": r.tax_type, "jurisdiction": r.jurisdiction,
             "rate": r.rate, "progressive": r.is_progressive} for r in rules]


# ═══════════════════════════════════════════════════════════════════════
# Financial Reports
# ═══════════════════════════════════════════════════════════════════════

@router.get("/reports")
async def list_reports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(FinancialReport).where(FinancialReport.tenant_id == tenant_id).order_by(FinancialReport.created_at.desc()).limit(200))
    reports = q.scalars().all()
    return [{"id": r.id, "type": r.report_type.value, "title": r.title, "status": r.status.value,
             "period": f"{r.period_start} to {r.period_end}", "ai_anomalies": len(r.ai_anomalies or []),
             "generated_at": str(r.generated_at) if r.generated_at else None} for r in reports]


# ═══════════════════════════════════════════════════════════════════════
# Audit & Compliance
# ═══════════════════════════════════════════════════════════════════════

@router.get("/audit/findings")
async def list_audit_findings(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(AuditFinding).where(AuditFinding.tenant_id == tenant_id)
    if status:
        q = q.where(AuditFinding.status == status)
    result = await db.execute(q.limit(200))
    findings = result.scalars().all()
    return [{"id": f.id, "number": f.finding_number, "title": f.title, "severity": f.severity.value,
             "status": f.status.value, "area": f.area, "impact": float(f.financial_impact or 0),
             "owner": f.remediation_owner, "ai_detected": f.ai_detected} for f in findings]

@router.get("/sox-controls")
async def list_sox_controls(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(SOXControl).where(SOXControl.tenant_id == tenant_id).limit(200))
    controls = q.scalars().all()
    return [{"id": c.id, "code": c.control_id_code, "name": c.name, "type": c.control_type,
             "frequency": c.frequency, "nature": c.nature, "area": c.area, "status": c.status.value,
             "risk_level": c.risk_level, "ai_score": c.ai_effectiveness_score} for c in controls]

@router.get("/compliance-rules")
async def list_compliance_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(FinanceComplianceRule).where(FinanceComplianceRule.tenant_id == tenant_id).where(FinanceComplianceRule.is_active == True).limit(200))
    rules = q.scalars().all()
    return [{"id": r.id, "regulation": r.regulation, "section": r.section, "name": r.name,
             "severity": r.severity, "is_blocking": r.is_blocking, "applies_to": r.applies_to} for r in rules]


# ═══════════════════════════════════════════════════════════════════════
# Agent Execution Triggers
# ═══════════════════════════════════════════════════════════════════════

@router.post("/invoices/{invoice_id}/match")
async def run_ap_agent(invoice_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Triggers the Accounts Payable agent to perform 3-way matching."""
    tenant_id = tenant["tenant_id"]
    from app.finance.agents.ap_agent import APAgent
    agent = APAgent()
    try:
        result = await agent.process_invoice(db, invoice_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="invoice", resource_id=invoice_id,
        )
        return result
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.post("/receivables/{invoice_id}/dunning")
async def run_ar_agent(invoice_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Triggers the Accounts Receivable agent to generate dunning letters."""
    tenant_id = tenant["tenant_id"]
    from app.finance.agents.ar_agent import ARAgent
    agent = ARAgent()
    try:
        result = await agent.generate_dunning(db, invoice_id, tenant_id)
        # Ensure the letter body is passed as 'letter' as expected by the frontend
        result["letter"] = f"Subject: {result.get('subject')}\n\n{result.get('body')}"
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="receivable", resource_id=invoice_id,
        )
        return result
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import TransitionRequest, apply_transition, list_workflow_events  # noqa: E402
from app.finance.services.analytics import finance_analytics  # noqa: E402
from app.finance.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_finance_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed KPIs, distributions and insights for the finance cockpit."""
    return await finance_analytics(db, tenant_id)


@router.get("/workflows")
async def get_finance_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines — the frontend renders transition actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_finance_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for finance entities."""
    return await list_workflow_events(db, tenant_id, domain="finance",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/invoices/{invoice_id}/transition")
async def transition_invoice(
    invoice_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded AP invoice lifecycle action (submit, approve, dispute, pay, void)."""
    return await apply_transition(db, WORKFLOW_SPECS["invoice"], invoice_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/expense-reports/{report_id}/transition")
async def transition_expense_report(
    report_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded expense report lifecycle action (submit, approve, reject, reimburse)."""
    return await apply_transition(db, WORKFLOW_SPECS["expense_report"], report_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
import uuid as _uuid_mod  # noqa: E402
from datetime import date as _date  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class ExpenseReportCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)
    employee_id: str
    total_amount: float = Field(..., gt=0)
    description: Optional[str] = None
    department: Optional[str] = Field(None, max_length=64)


@router.post("/expense-reports", status_code=201)
async def create_expense_report(
    body: ExpenseReportCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """File an expense report (starts DRAFT; submit/approve via /transition)."""
    tenant_id = tenant["tenant_id"]
    rep = ExpenseReport(
        tenant_id=tenant_id,
        report_number=f"EXP-{_uuid_mod.uuid4().hex[:8].upper()}",
        title=body.title, employee_id=body.employee_id,
        total_amount=body.total_amount, description=body.description,
        department=body.department,
    )
    db.add(rep)
    await db.commit()
    await db.refresh(rep)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="expense_report", resource_id=rep.id,
    )
    return {"id": rep.id, "number": rep.report_number, "title": rep.title,
            "status": rep.status.value if hasattr(rep.status, "value") else str(rep.status),
            "total": float(rep.total_amount or 0)}


class InvoiceCreate(BaseModel):
    vendor_id: str
    invoice_number: Optional[str] = Field(None, max_length=64)
    invoice_date: _date
    due_date: _date
    subtotal: float = Field(..., gt=0)
    tax_amount: float = Field(0, ge=0)
    po_number: Optional[str] = Field(None, max_length=64)


@router.post("/invoices", status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Register an AP invoice (starts DRAFT; approval/payment via /transition)."""
    tenant_id = tenant["tenant_id"]
    vendor_q = await db.execute(select(Vendor).where(
        Vendor.id == body.vendor_id, Vendor.tenant_id == tenant_id))
    if not vendor_q.scalar_one_or_none():
        raise HTTPException(404, "Vendor not found")
    total = body.subtotal + body.tax_amount
    inv = Invoice(
        tenant_id=tenant_id, vendor_id=body.vendor_id,
        invoice_number=body.invoice_number or f"INV-{_uuid_mod.uuid4().hex[:8].upper()}",
        invoice_date=body.invoice_date, due_date=body.due_date,
        subtotal=body.subtotal, tax_amount=body.tax_amount,
        total_amount=total, balance_due=total, po_number=body.po_number,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="invoice", resource_id=inv.id,
    )
    return {"id": inv.id, "number": inv.invoice_number,
            "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
            "total": float(inv.total_amount), "balance": float(inv.balance_due)}
